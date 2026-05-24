import Foundation

@MainActor
final class PurchaseManager: ObservableObject {

    nonisolated init() {}

    static func uuidFromHex(_ value: String) -> UUID? {
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
