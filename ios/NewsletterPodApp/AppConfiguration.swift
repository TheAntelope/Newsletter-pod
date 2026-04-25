import Foundation

enum AppConfiguration {
    static let baseURL = URL(string: "https://newsletter-pod-497154432194.europe-west1.run.app")!
    static let monthlyProductID = "com.newsletterpod.paid.monthly"
    static let annualProductID = "com.newsletterpod.paid.annual"

    static var termsURL: URL { baseURL.appendingPathComponent("legal/terms") }
    static var privacyURL: URL { baseURL.appendingPathComponent("legal/privacy") }
}
