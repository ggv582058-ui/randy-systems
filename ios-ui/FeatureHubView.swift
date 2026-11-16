import SwiftUI
import UIKit

// A distinct Randy Mod interface. Original 3106 functionality and attribution
// are preserved; the dashboard does not pretend to validate license keys.
struct FeatureHubView: View {
    @Environment(\.appLanguage) private var language
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @EnvironmentObject private var appState: AppState
    @AppStorage("rs.control.selectedProfile") private var selectedProfile = 0
    @State private var licensePresented = false
    @State private var expandTools = false

    let onSelectTab: (AppSection) -> Void
    let onOpenSettings: () -> Void
    let onOpenLogs: () -> Void

    private let cyan = Color(red: 0.18, green: 0.82, blue: 1.00)
    private let gold = Color(red: 1.00, green: 0.76, blue: 0.27)
    private let muted = Color(red: 0.59, green: 0.70, blue: 0.78)

    var body: some View {
        NavigationStack {
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 25) {
                    topBanner
                    hero
                    profileSection
                    primaryActions
                    workbenchSection
                    footer
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 22)
                .frame(maxWidth: 680)
                .frame(maxWidth: .infinity)
            }
            .background(RSAtmosphere().ignoresSafeArea())
            .navigationTitle("RS CONTROL")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        licensePresented = true
                    } label: {
                        Label("Licencia", systemImage: "key.horizontal.fill")
                            .font(.subheadline.weight(.medium))
                    }
                }
            }
            .sheet(isPresented: $licensePresented) {
                RSLicenseControlView()
                    .preferredColorScheme(.dark)
            }
        }
    }

    private var topBanner: some View {
        HStack(spacing: 7) {
            Circle().fill(cyan).frame(width: 6, height: 6)
                .shadow(color: cyan.opacity(0.9), radius: 6)
            Text("RS  /  EXTERNAL IOS")
                .tracking(2.1)
            Spacer()
            Image(systemName: "shield.lefthalf.filled")
            Text("CONTROL 01")
                .tracking(1.1)
        }
        .font(.system(size: 10, weight: .semibold, design: .monospaced))
        .foregroundStyle(cyan)
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .center, spacing: 18) {
                AppLogo(size: 88)
                    .shadow(color: cyan.opacity(0.50), radius: 22)
                    .overlay(
                        RoundedRectangle(cornerRadius: 20)
                            .strokeBorder(cyan.opacity(0.42), lineWidth: 1)
                    )
                VStack(alignment: .leading, spacing: 5) {
                    Text("RANDY")
                        .font(.system(size: 37, weight: .black, design: .rounded))
                        .tracking(1.4)
                        .foregroundStyle(.white)
                        .minimumScaleFactor(0.7)
                        .lineLimit(1)
                    Text("MOD  /  STUDIO")
                        .font(.system(size: 12, weight: .bold, design: .monospaced))
                        .tracking(2.1)
                        .foregroundStyle(gold)
                    Text("YOUR SPACE. YOUR TOOLS.")
                        .font(.system(size: 9, weight: .medium, design: .monospaced))
                        .tracking(0.5)
                        .foregroundStyle(muted)
                }
                Spacer(minLength: 0)
            }
            Rectangle().fill(
                LinearGradient(colors: [cyan, gold.opacity(0.8), .clear],
                               startPoint: .leading, endPoint: .trailing)
            ).frame(height: 1)
            HStack {
                Label("Panel de herramientas", systemImage: "square.stack.3d.up.fill")
                Spacer()
                Text("v" + AppInfo.appVersion)
                    .fontDesign(.monospaced)
            }
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(muted)
        }
        .padding(22)
        .background(
            LinearGradient(colors: [Color(red: 0.06, green: 0.17, blue: 0.31),
                                    Color(red: 0.025, green: 0.068, blue: 0.13)],
                           startPoint: .topLeading, endPoint: .bottomTrailing),
            in: RoundedRectangle(cornerRadius: 26)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 26)
                .strokeBorder(
                    LinearGradient(colors: [cyan.opacity(0.6), gold.opacity(0.46),
                                            cyan.opacity(0.12)],
                                   startPoint: .topLeading, endPoint: .bottomTrailing),
                    lineWidth: 1
                )
        )
    }

    private var profileSection: some View {
        VStack(alignment: .leading, spacing: 13) {
            sectionKicker("01  /  PERFIL")
            HStack(alignment: .firstTextBaseline) {
                Text("Selecciona tu espacio")
                    .font(.system(size: 23, weight: .bold, design: .rounded))
                    .foregroundStyle(.white)
                Spacer()
            }
            Text("Personaliza tu vista. Los parches usan la biblioteca local existente.")
                .font(.caption)
                .foregroundStyle(muted)
            HStack(spacing: 12) {
                profileCard(0, title: "FREE FIRE",
                            sub: "ESTÁNDAR", icon: "scope", index: "01")
                profileCard(1, title: "FF MAX",
                            sub: "MAX", icon: "bolt.shield.fill", index: "02")
            }
            HStack(spacing: 7) {
                Image(systemName: "checkmark.seal.fill").foregroundStyle(cyan)
                Text(selectedProfile == 0 ? "Perfil estándar seleccionado" : "Perfil MAX seleccionado")
                    .foregroundStyle(muted)
            }
            .font(.system(size: 11, weight: .medium))
            .padding(.top, 2)
        }
    }

    private func profileCard(_ option: Int, title: String,
                             sub: String, icon: String,
                             index: String) -> some View {
        let active = selectedProfile == option
        return Button {
            if reduceMotion {
                selectedProfile = option
            } else {
                withAnimation(.easeInOut(duration: 0.2)) {
                    selectedProfile = option
                }
            }
        } label: {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text(index)
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .foregroundStyle(active ? cyan : muted)
                    Spacer()
                    Image(systemName: active ? "checkmark.circle.fill" : "circle")
                        .foregroundStyle(active ? cyan : muted)
                }
                ZStack {
                    Circle()
                        .strokeBorder(active ? cyan.opacity(0.65) : muted.opacity(0.22), lineWidth: 1)
                        .frame(width: 65, height: 65)
                    Image(systemName: icon)
                        .font(.system(size: 26, weight: .thin))
                        .foregroundStyle(active ? cyan : .white.opacity(0.8))
                }
                .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 3) {
                    Text(title)
                        .font(.system(size: 16, weight: .bold, design: .rounded))
                        .foregroundStyle(.white)
                        .lineLimit(1)
                        .minimumScaleFactor(0.74)
                    Text(sub)
                        .font(.system(size: 10, weight: .medium, design: .monospaced))
                        .tracking(1)
                        .foregroundStyle(active ? gold : muted)
                }
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 200, alignment: .topLeading)
            .background(
                LinearGradient(colors: active
                    ? [Color(red: 0.06, green: 0.23, blue: 0.35),
                       Color(red: 0.035, green: 0.09, blue: 0.17)]
                    : [Color(red: 0.08, green: 0.12, blue: 0.18),
                       Color(red: 0.035, green: 0.065, blue: 0.10)],
                               startPoint: .topLeading, endPoint: .bottomTrailing),
                in: RoundedRectangle(cornerRadius: 20)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .strokeBorder(active ? cyan.opacity(0.65) : muted.opacity(0.28), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title + (active ? ", seleccionado" : ", elegir"))
    }

    private var primaryActions: some View {
        VStack(alignment: .leading, spacing: 13) {
            sectionKicker("02  /  ACCESO RÁPIDO")
            NavigationLink {
                PatchProjectsView(
                    onOpenSettings: onOpenSettings,
                    onOpenLogs: onOpenLogs
                )
            } label: {
                HStack(spacing: 15) {
                    Image(systemName: "shippingbox.fill")
                        .font(.system(size: 24))
                        .foregroundStyle(Color(red: 0.03, green: 0.12, blue: 0.20))
                        .frame(width: 50, height: 50)
                        .background(cyan, in: RoundedRectangle(cornerRadius: 15))
                    VStack(alignment: .leading, spacing: 4) {
                        Text("PATCH STUDIO")
                            .font(.system(size: 18, weight: .heavy, design: .rounded))
                            .foregroundStyle(.white)
                        Text("Abrir biblioteca e importar paquetes")
                            .font(.caption)
                            .foregroundStyle(muted)
                    }
                    Spacer(minLength: 0)
                    Image(systemName: "arrow.up.right")
                        .foregroundStyle(gold)
                }
                .padding(18)
                .background(
                    LinearGradient(colors: [Color(red: 0.08, green: 0.24, blue: 0.34),
                                            Color(red: 0.025, green: 0.09, blue: 0.16)],
                                   startPoint: .leading, endPoint: .trailing),
                    in: RoundedRectangle(cornerRadius: 20)
                )
                .overlay(RoundedRectangle(cornerRadius: 20)
                    .strokeBorder(cyan.opacity(0.55), lineWidth: 1))
            }
            .buttonStyle(.plain)

            Button {
                onSelectTab(.files)
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "folder.badge.gearshape")
                        .font(.title3)
                        .foregroundStyle(gold)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("APP DATA")
                            .font(.system(size: 15, weight: .bold))
                            .foregroundStyle(.white)
                        Text("Explorador de archivos")
                            .font(.caption)
                            .foregroundStyle(muted)
                    }
                    Spacer()
                    Image(systemName: "arrow.right").foregroundStyle(cyan)
                }
                .padding(18)
                .background(
                    Color(red: 0.06, green: 0.12, blue: 0.19),
                    in: RoundedRectangle(cornerRadius: 18)
                )
                .overlay(RoundedRectangle(cornerRadius: 18)
                    .strokeBorder(gold.opacity(0.35), lineWidth: 1))
            }
            .buttonStyle(.plain)
        }
    }

    private var workbenchSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                sectionKicker("03  /  WORKBENCH")
                Spacer()
                Button {
                    if reduceMotion { expandTools.toggle() }
                    else { withAnimation(.easeInOut(duration: 0.22)) { expandTools.toggle() } }
                } label: {
                    Label(expandTools ? "Ver menos" : "Ver todo",
                          systemImage: expandTools ? "chevron.up" : "chevron.down")
                        .font(.caption.weight(.medium))
                }
                .foregroundStyle(cyan)
            }
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12),
                                GridItem(.flexible(), spacing: 12)], spacing: 12) {
                NavigationLink {
                    RepositoryNewView(onOpenSettings: onOpenSettings, onOpenLogs: onOpenLogs)
                } label: {
                    workTile("Catálogo", "Paquetes", "square.grid.2x2.fill")
                }
                NavigationLink {
                    BackupCenterView()
                } label: {
                    workTile("Respaldos", "Guardar y recuperar", "externaldrive.fill")
                }
                NavigationLink {
                    FileReplaceView()
                } label: {
                    workTile("Reemplazar", "Archivos", "arrow.triangle.2.circlepath")
                }
                Button(action: onOpenLogs) {
                    workTile("Diagnóstico", "Registros", "waveform.path.ecg")
                }
                if expandTools {
                    NavigationLink {
                        RepositorySourcesView(onOpenSettings: onOpenSettings, onOpenLogs: onOpenLogs)
                    } label: {
                        workTile("Fuentes", "Repositorios", "shippingbox.fill")
                    }
                    NavigationLink {
                        MigrationView()
                    } label: {
                        workTile("Migración", "Transferir datos", "arrow.left.arrow.right")
                    }
                    NavigationLink {
                        AcknowledgementsView()
                    } label: {
                        workTile("Créditos", "Proyecto original", "text.book.closed")
                    }
                    Button(action: onOpenSettings) {
                        workTile("Ajustes", "Preferencias", "slider.horizontal.3")
                    }
                }
            }
            .buttonStyle(.plain)
        }
    }

    private func workTile(_ title: String, _ detail: String, _ symbol: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 22, weight: .light))
                .foregroundStyle(cyan)
                .frame(width: 38, height: 38)
                .background(cyan.opacity(0.12), in: RoundedRectangle(cornerRadius: 11))
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(.white)
                Text(detail).font(.system(size: 11))
                    .foregroundStyle(muted)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
        }
        .frame(maxWidth: .infinity, minHeight: 110, alignment: .topLeading)
        .padding(15)
        .background(Color(red: 0.045, green: 0.105, blue: 0.175),
                    in: RoundedRectangle(cornerRadius: 17))
        .overlay(RoundedRectangle(cornerRadius: 17)
            .strokeBorder(cyan.opacity(0.2), lineWidth: 1))
    }

    private func sectionKicker(_ text: String) -> some View {
        HStack(spacing: 8) {
            Capsule().fill(cyan).frame(width: 23, height: 3)
            Text(text)
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .tracking(2)
                .foregroundStyle(cyan)
        }
    }

    private var footer: some View {
        VStack(spacing: 10) {
            HStack {
                Image(systemName: appState.isSupported ? "checkmark.shield" : "exclamationmark.shield")
                    .foregroundStyle(appState.isSupported ? cyan : gold)
                Text("Motor: " + SandboxAccess.backend.displayName)
                Spacer()
                Text("RS / 2026")
            }
            .font(.system(size: 11, weight: .medium, design: .monospaced))
            .foregroundStyle(muted)
            Text("Randy Mod es una personalización del proyecto de código abierto 3106.")
                .font(.system(size: 10))
                .foregroundStyle(muted.opacity(0.75))
                .multilineTextAlignment(.center)
        }
        .padding(.top, 6)
        .padding(.bottom, 25)
    }
}

private struct RSAtmosphere: View {
    var body: some View {
        GeometryReader { geo in
            ZStack {
                Color(red: 0.011, green: 0.026, blue: 0.053)
                RadialGradient(colors: [Color.cyan.opacity(0.22), .clear],
                               center: UnitPoint(x: 0.82, y: 0.12),
                               startRadius: 30, endRadius: 370)
                RadialGradient(colors: [Color(red: 0.44, green: 0.30, blue: 0.08).opacity(0.12), .clear],
                               center: UnitPoint(x: 0.1, y: 0.6),
                               startRadius: 15, endRadius: 300)
                Path { path in
                    let step: CGFloat = 34
                    for x in stride(from: CGFloat(0), through: geo.size.width, by: step) {
                        path.move(to: CGPoint(x: x, y: 0))
                        path.addLine(to: CGPoint(x: x, y: geo.size.height))
                    }
                    for y in stride(from: CGFloat(0), through: geo.size.height, by: step) {
                        path.move(to: CGPoint(x: 0, y: y))
                        path.addLine(to: CGPoint(x: geo.size.width, y: y))
                    }
                }
                .stroke(Color.cyan.opacity(0.045), lineWidth: 0.5)
            }
        }
        .allowsHitTesting(false)
    }
}

private struct RSLicenseControlView: View {
    @Environment(\.dismiss) private var dismiss
    private let cyan = Color(red: 0.18, green: 0.82, blue: 1.00)

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    HStack(spacing: 16) {
                        AppLogo(size: 72)
                        VStack(alignment: .leading, spacing: 4) {
                            Text("ACCESO RS")
                                .font(.system(size: 25, weight: .heavy, design: .rounded))
                            Text("CONTROL DE LICENCIA")
                                .font(.system(size: 10, weight: .medium, design: .monospaced))
                                .tracking(2).foregroundStyle(cyan)
                        }
                    }
                    .padding(.top, 15)

                    VStack(alignment: .leading, spacing: 12) {
                        Label("Integración pendiente", systemImage: "key.slash.fill")
                            .font(.headline)
                            .foregroundStyle(.yellow)
                        Text("La verificación de keys requiere conectar tu API de licencias. Esta compilación no valida claves ni inventa sesiones activas.")
                            .font(.subheadline)
                            .foregroundStyle(.white.opacity(0.78))
                        Divider()
                        HStack {
                            Text("Estado")
                            Spacer()
                            Text("Sin conectar").foregroundStyle(.yellow)
                        }
                        HStack {
                            Text("Sistema")
                            Spacer()
                            Text("iOS " + UIDevice.current.systemVersion)
                        }
                        HStack {
                            Text("Dispositivo")
                            Spacer()
                            Text(UIDevice.current.model)
                        }
                    }
                    .font(.subheadline)
                    .padding(20)
                    .background(Color(red: 0.06, green: 0.13, blue: 0.21),
                                in: RoundedRectangle(cornerRadius: 22))
                    .overlay(RoundedRectangle(cornerRadius: 22)
                        .strokeBorder(cyan.opacity(0.4), lineWidth: 1))

                    Text("Para habilitar el inicio de sesión real, la expiración y el límite por dispositivo se necesita un servidor que valide las keys. No guardes claves en una interfaz sin verificación.")
                        .font(.caption)
                        .foregroundStyle(.gray)
                }
                .padding(20)
            }
            .background(RSAtmosphere().ignoresSafeArea())
            .navigationTitle("Licencia")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Listo") { dismiss() }
                }
            }
        }
    }
}
