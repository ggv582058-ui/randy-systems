"""Private iOS app signing for completed certificate orders."""

from __future__ import annotations

import io
import os
import plistlib
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path


KINDS = {"gbox": "GBox", "esign": "ESign"}
ZSIGN_REVISION = "614caa8d1ca949e260e5746144aa52d27a4b08d6"


class SigningError(ValueError):
    pass


def ipa_info(data: bytes) -> tuple[str, str]:
    if len(data) > 25 * 1024 * 1024 or len(data) < 1024:
        raise SigningError("La IPA debe pesar entre 1 KB y 25 MB")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            files = archive.infolist()
            if len(files) > 3000 or sum(entry.file_size for entry in files) > 150 * 1024 * 1024:
                raise SigningError("IPA demasiado grande para procesar")
            if any(name.filename.startswith("/") or "\\" in name.filename or
                   ".." in name.filename.split("/") for name in files):
                raise SigningError("La IPA contiene rutas inseguras")
            roots = [n.removesuffix("Info.plist") for n in archive.namelist()
                     if n.startswith("Payload/") and n.count("/") == 2 and
                     n.endswith(".app/Info.plist")]
            if len(roots) != 1:
                raise SigningError("No encontré una aplicación iOS dentro de Payload")
            info = plistlib.loads(archive.read(roots[0] + "Info.plist"))
            bundle_id = info.get("CFBundleIdentifier")
            version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
            executable = info.get("CFBundleExecutable")
            if not all(isinstance(v, str) and v for v in (bundle_id, version, executable)):
                raise SigningError("La IPA no contiene metadatos válidos")
            if roots[0] + executable not in archive.namelist():
                raise SigningError("La IPA no contiene el ejecutable de la aplicación")
            return bundle_id, version
    except (zipfile.BadZipFile, KeyError, plistlib.InvalidFileException, TypeError) as exc:
        raise SigningError("Archivo IPA/ZIP inválido") from exc


def profile_info(data: bytes, udid: str, bundle_id: str) -> str:
    result = subprocess.run(["openssl", "cms", "-verify", "-inform", "DER", "-noverify"],
                            input=data, capture_output=True, timeout=15)
    if result.returncode:
        raise SigningError("MobileProvision inválido")
    try:
        profile = plistlib.loads(result.stdout)
        expiry = profile["ExpirationDate"]
        expires = expiry.replace(tzinfo=timezone.utc) if expiry.tzinfo is None else expiry
        app_id = profile["Entitlements"]["application-identifier"].split(".", 1)[1]
    except (KeyError, ValueError, TypeError, plistlib.InvalidFileException, AttributeError) as exc:
        raise SigningError("El perfil no contiene fecha o identificador válidos") from exc
    if expires <= datetime.now(timezone.utc):
        raise SigningError("El MobileProvision ya venció")
    devices = profile.get("ProvisionedDevices", [])
    if not profile.get("ProvisionsAllDevices") and udid.upper() not in [str(d).upper() for d in devices]:
        raise SigningError("Este perfil no incluye el UDID del comprador")
    if app_id == "*" or app_id == bundle_id or (app_id.endswith(".*") and
                                                  bundle_id.startswith(app_id[:-1])):
        return bundle_id
    # Exact App ID: zsign can change the bundle ID to match the profile.
    if "*" not in app_id and app_id:
        return app_id
    raise SigningError("El Bundle ID no coincide con el MobileProvision")


def ensure_signer(cache: Path) -> Path:
    configured = os.getenv("ZSIGN_BIN", "").strip()
    if configured:
        path = Path(configured)
        if path.is_file() and os.access(path, os.X_OK):
            return path
        raise SigningError("El firmador configurado no está disponible")
    source = cache / "zsign-src"
    binary = source / "bin" / "zsign"
    if binary.is_file() and os.access(binary, os.X_OK):
        return binary
    cache.mkdir(parents=True, exist_ok=True)
    try:
        if not source.exists():
            subprocess.run(["git", "clone", "--depth", "1", "https://github.com/zhlynn/zsign.git",
                            str(source)], check=True, capture_output=True, timeout=90)
        revision = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True, timeout=10).stdout.strip()
        if revision != ZSIGN_REVISION:
            raise SigningError("La versión del firmador cambió; necesita revisión")
        subprocess.run(["make", "-C", str(source / "build" / "linux"), "-j2",
                        "OPENSSL_LIB=-lssl -lcrypto"], check=True, capture_output=True, timeout=240)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SigningError("No se pudo compilar el firmador en este servidor") from exc
    if not binary.is_file():
        raise SigningError("No se generó el ejecutable para firmar")
    return binary


def sign_ipa(data: bytes, cert_zip: bytes, password: str, udid: str, cache: Path) -> tuple[bytes, str, str]:
    source_id, _ = ipa_info(data)
    try:
        with zipfile.ZipFile(io.BytesIO(cert_zip)) as archive:
            p12 = next(archive.read(n) for n in archive.namelist()
                       if n.lower().endswith((".p12", ".pfx")))
            provision = next(archive.read(n) for n in archive.namelist()
                             if n.lower().endswith((".mobileprovision", ".provisionprofile")))
    except (zipfile.BadZipFile, StopIteration) as exc:
        raise SigningError("El proveedor no entregó P12 y MobileProvision") from exc
    target_id = profile_info(provision, udid, source_id)
    signer = ensure_signer(cache)
    with tempfile.TemporaryDirectory(prefix="randy-sign-") as directory:
        root = Path(directory)
        incoming, cert, mobile, output = (root / f for f in ("source.ipa", "cert.p12", "profile.mobileprovision", "signed.ipa"))
        incoming.write_bytes(data)
        cert.write_bytes(p12)
        mobile.write_bytes(provision)
        try:
            result = subprocess.run([str(signer), "-k", str(cert), "-p", password,
                                     "-m", str(mobile), "-b", target_id, "-o", str(output),
                                     str(incoming)], cwd=directory, capture_output=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SigningError("No se completó la firma de la aplicación") from exc
        if result.returncode or not output.is_file():
            raise SigningError("El certificado no pudo firmar esta aplicación")
        signed = output.read_bytes()
    signed_id, version = ipa_info(signed)
    if signed_id != target_id:
        raise SigningError("La IPA firmada no coincide con el perfil")
    return signed, signed_id, version
