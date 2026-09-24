import SwiftUI

@main
struct {{IDENT}}App: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

struct RootView: View {
    var body: some View {
        TabView {
            Tab("Home", systemImage: "sparkles") {
                NavigationStack { HomeView() }
            }
            Tab("Sensors", systemImage: "gauge.with.dots.needle.67percent") {
                NavigationStack { SensorsView() }
            }
            Tab("Camera", systemImage: "camera") {
                NavigationStack { CameraView() }
            }
        }
        // Liquid Glass tab bar shrinks while scrolling (iOS 26).
        .tabBarMinimizeBehavior(.onScrollDown)
    }
}

struct HomeView: View {
    @State private var expanded = false
    @State private var taps = 0
    @Namespace private var glass

    var body: some View {
        ZStack {
            LinearGradient(colors: [.indigo, .purple, .orange],
                           startPoint: .topLeading, endPoint: .bottomTrailing)
                .ignoresSafeArea()

            VStack(spacing: 28) {
                Text("{{NAME}}")
                    .font(.largeTitle.bold())
                    .padding(.horizontal, 28).padding(.vertical, 14)
                    .glassEffect(.regular.interactive(), in: .capsule)

                // Glass shapes inside a container blend and morph into each other.
                GlassEffectContainer(spacing: 24) {
                    HStack(spacing: 24) {
                        Image(systemName: "sun.max.fill")
                            .font(.title).frame(width: 72, height: 72)
                            .glassEffect(.regular.tint(.orange.opacity(0.4)).interactive())
                            .glassEffectID("sun", in: glass)
                        if expanded {
                            Image(systemName: "moon.stars.fill")
                                .font(.title).frame(width: 72, height: 72)
                                .glassEffect(.regular.tint(.blue.opacity(0.4)).interactive())
                                .glassEffectID("moon", in: glass)
                        }
                    }
                }

                HStack {
                    Button(expanded ? "Merge" : "Split") {
                        withAnimation(.bouncy) { expanded.toggle() }
                    }
                    .buttonStyle(.glass)

                    Button("Tapped \(taps)") { taps += 1 }
                        .buttonStyle(.glassProminent)
                        .sensoryFeedback(.impact, trigger: taps)
                }
            }
            .foregroundStyle(.white)
        }
        .navigationTitle("Liquid Glass")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                ShareLink(item: "Built on Linux with TuxSign")
            }
        }
    }
}
