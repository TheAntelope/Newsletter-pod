import SwiftUI
import UIKit

@main
struct NewsletterPodApp: App {
    @StateObject private var viewModel = AppViewModel()

    init() {
        // iOS 26 SwiftUI runs continuous animations on Form views (Liquid
        // Glass etc.) which causes XCUITest's "wait for idle" to time out
        // with "Unable to monitor animations" — every element query on the
        // affected screen then misses. SwiftUI animations route through
        // UIKit, so disabling UIView animations under the UI-test seed
        // makes the views queryable without changing production behavior.
        if ProcessInfo.processInfo.arguments.contains("-uiTestMode") {
            UIView.setAnimationsEnabled(false)
        }
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(viewModel)
                .preferredColorScheme(.light)
                .task {
                    await viewModel.purchaseManager.loadProducts()
                }
        }
    }
}
