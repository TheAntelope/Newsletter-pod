import Foundation
import StoreKit

private struct VerificationError: Error {}

@MainActor
final class PurchaseManager: ObservableObject {

    nonisolated init() {}
    @Published var products: [Product] = []
    @Published var isLoading = false
    @Published var lastPurchaseMessage: String?

    func loadProducts() async {
        isLoading = true
        defer { isLoading = false }

        do {
            products = try await Product.products(for: [
                AppConfiguration.monthlyProductID,
                AppConfiguration.annualProductID,
            ])
            products.sort { $0.price < $1.price }
        } catch {
            lastPurchaseMessage = error.localizedDescription
        }
    }

    func purchase(product: Product, userID: String) async {
        do {
            let accountToken = uuidFromHex(userID) ?? UUID()
            let result = try await product.purchase(options: [.appAccountToken(accountToken)])
            switch result {
            case .success(let verification):
                let transaction = try checkVerified(verification)
                await transaction.finish()
                lastPurchaseMessage = "Purchase successful."
            case .userCancelled:
                lastPurchaseMessage = "Purchase cancelled."
            case .pending:
                lastPurchaseMessage = "Purchase pending approval."
            @unknown default:
                lastPurchaseMessage = "Unknown purchase state."
            }
        } catch {
            lastPurchaseMessage = error.localizedDescription
        }
    }

    private func checkVerified<T>(_ result: VerificationResult<T>) throws -> T {
        switch result {
        case .unverified:
            throw VerificationError()
        case .verified(let safe):
            return safe
        }
    }

    private func uuidFromHex(_ value: String) -> UUID? {
        guard value.count == 32 else { return nil }
        let formatted = [
            value.prefix(8),
            value.dropFirst(8).prefix(4),
            value.dropFirst(12).prefix(4),
            value.dropFirst(16).prefix(4),
            value.dropFirst(20).prefix(12),
        ].map(String.init).joined(separator: "-")
        return UUID(uuidString: formatted)
    }
}
