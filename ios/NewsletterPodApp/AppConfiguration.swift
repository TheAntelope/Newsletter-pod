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
}
