import SwiftUI
import WebKit

/// Native host for TuxSign HTML apps: a full-screen WKWebView that loads
/// www/index.html, a JavaScript bridge to every sensor, and a real
/// Liquid Glass toolbar the page can populate with `tux.ui.setToolbar`.
@main
struct TuxShellApp: App {
    var body: some Scene {
        WindowGroup { ShellView() }
    }
}

struct ToolbarItemSpec: Identifiable, Equatable {
    let id: String
    let icon: String
    let title: String?
}

@MainActor
@Observable
final class ShellState {
    var toolbar: [ToolbarItemSpec] = []
    var tint: Color? = nil
    let bridge = Bridge()

    init() { bridge.state = self }
}

struct ShellView: View {
    @State private var state = ShellState()

    var body: some View {
        ZStack(alignment: .bottom) {
            WebView(bridge: state.bridge).ignoresSafeArea()
            if !state.toolbar.isEmpty {
                GlassEffectContainer(spacing: 12) {
                    HStack(spacing: 12) {
                        ForEach(state.toolbar) { item in
                            Button {
                                state.bridge.emit("toolbar", ["id": item.id])
                            } label: {
                                if let title = item.title {
                                    Label(title, systemImage: item.icon)
                                } else {
                                    Image(systemName: item.icon)
                                }
                            }
                            .buttonStyle(.glass)
                            .tint(state.tint)
                        }
                    }
                }
                .padding(.bottom, 12)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.bouncy, value: state.toolbar)
    }
}

struct WebView: UIViewRepresentable {
    let bridge: Bridge

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.mediaTypesRequiringUserActionForPlayback = []
        config.preferences.javaScriptCanOpenWindowsAutomatically = true
        config.userContentController.addUserScript(
            WKUserScript(source: Bridge.javascript, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        config.userContentController.addScriptMessageHandler(bridge, contentWorld: .page, name: "tux")

        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = .clear
        web.scrollView.contentInsetAdjustmentBehavior = .never
        web.allowsBackForwardNavigationGestures = true
        web.isInspectable = true
        bridge.webView = web

        let root = Bundle.main.bundleURL.appendingPathComponent("www", isDirectory: true)
        web.loadFileURL(root.appendingPathComponent("index.html"), allowingReadAccessTo: root)
        return web
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
