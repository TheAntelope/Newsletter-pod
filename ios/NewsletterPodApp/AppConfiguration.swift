import Foundation

enum AppConfiguration {
    static let baseURL = URL(string: "https://newsletter-pod-497154432194.europe-west1.run.app")!

    // StoreKit subscription products. Four SKUs spanning the Pro/Max tiers,
    // each with a monthly and annual option. Order matters: paywall renders
    // products in `allProductIDs` order when StoreKit returns them.
    static let proMonthlyProductID = "com.newsletterpod.pro.monthly"
    static let proAnnualProductID = "com.newsletterpod.pro.annual"
    static let maxMonthlyProductID = "com.newsletterpod.max.monthly"
    static let maxAnnualProductID = "com.newsletterpod.max.annual"

    static let proProductIDs: Set<String> = [proMonthlyProductID, proAnnualProductID]
    static let maxProductIDs: Set<String> = [maxMonthlyProductID, maxAnnualProductID]

    static let allProductIDs: [String] = [
        proMonthlyProductID,
        proAnnualProductID,
        maxMonthlyProductID,
        maxAnnualProductID,
    ]

    static var termsURL: URL { baseURL.appendingPathComponent("legal/terms") }
    static var privacyURL: URL { baseURL.appendingPathComponent("legal/privacy") }

    /// Bundle identifier shipped to the backend on device-token registration
    /// so APNs `apns-topic` matches the build's signing identity.
    static var bundleIdentifier: String {
        Bundle.main.bundleIdentifier ?? "com.newsletterpod.app"
    }

    /// APNs environment for the current build. Matches `aps-environment`
    /// in the entitlements file:
    ///   - "production" for App Store / TestFlight builds
    ///   - "sandbox" for development builds running from Xcode
    /// We can't read the entitlements at runtime, so this mirrors the
    /// release configuration. If you switch the entitlement to sandbox for
    /// local debugging, flip this too or APNs will silently fail.
    static var apnsEnvironment: String {
        #if DEBUG
        return "sandbox"
        #else
        return "production"
        #endif
    }
}
