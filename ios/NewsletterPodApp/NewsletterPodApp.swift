import SwiftUI

@main
struct NewsletterPodApp: App {
    @StateObject private var viewModel = AppViewModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(viewModel)
                .task {
                    await viewModel.purchaseManager.loadProducts()
                }
        }
    }
}
