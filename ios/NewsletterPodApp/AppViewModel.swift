import Foundation

@MainActor
final class AppViewModel: ObservableObject {
    @Published var sessionToken: String?
    @Published var user: UserDTO?
    @Published var profile: PodcastProfileDTO?
    @Published var schedule: DeliveryScheduleDTO?
    @Published var subscription: SubscriptionDTO?
    @Published var entitlements: EntitlementsDTO?
    @Published var catalogSources: [CatalogSourceDTO] = []
    @Published var selectedSources: [UserSourceDTO] = []
    @Published var feed: FeedEnvelope?
    @Published var isLoading = false
    @Published var errorMessage: String?

    let apiClient: APIClient
    let purchaseManager: PurchaseManager

    init(apiClient: APIClient = APIClient(), purchaseManager: PurchaseManager = PurchaseManager()) {
        self.apiClient = apiClient
        self.purchaseManager = purchaseManager
    }

    var isAuthenticated: Bool { sessionToken != nil }
    var isPaid: Bool { subscription?.tier == "paid" }

    func signIn(identityToken: String) async {
        await load {
            let session = try await apiClient.signInWithApple(identityToken: identityToken)
            sessionToken = session.sessionToken
            user = session.user
            subscription = session.subscription
            try await refresh()
        }
    }

    func refresh() async throws {
        guard let sessionToken else { return }
        async let me = apiClient.fetchMe(token: sessionToken)
        async let catalog = apiClient.fetchCatalog()
        async let sources = apiClient.fetchSources(token: sessionToken)
        async let feed = apiClient.fetchFeed(token: sessionToken)

        let meValue = try await me
        let catalogValue = try await catalog
        let sourcesValue = try await sources
        let feedValue = try await feed

        user = meValue.user
        profile = meValue.profile
        schedule = meValue.schedule
        subscription = meValue.subscription
        entitlements = meValue.entitlements
        catalogSources = catalogValue.sources
        selectedSources = sourcesValue.sources
        self.feed = feedValue
    }

    func updateProfile(displayName: String, timezone: String) async {
        guard let sessionToken else { return }
        await load {
            let me = try await apiClient.updateProfile(token: sessionToken, displayName: displayName, timezone: timezone)
            user = me.user
            schedule = me.schedule
            subscription = me.subscription
            entitlements = me.entitlements
        }
    }

    func saveSources(catalogIDs: [String], customURLs: [String]) async {
        guard let sessionToken else { return }
        let catalogPayload = catalogIDs.map { SourcePayload(sourceID: $0, rssURL: nil, isCustom: nil) }
        let customPayload = customURLs
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .map { SourcePayload(sourceID: nil, rssURL: $0, isCustom: true) }

        await load {
            let response = try await apiClient.replaceSources(
                token: sessionToken,
                sources: catalogPayload + customPayload
            )
            selectedSources = response.sources
            entitlements = response.entitlements
            feed = try await apiClient.fetchFeed(token: sessionToken)
        }
    }

    func savePodcastConfig(
        title: String,
        formatPreset: String,
        primaryHost: String,
        secondaryHost: String?,
        guestNames: [String],
        desiredDurationMinutes: Int
    ) async {
        guard let sessionToken else { return }
        await load {
            let response = try await apiClient.updatePodcastConfig(
                token: sessionToken,
                title: title,
                formatPreset: formatPreset,
                hostPrimaryName: primaryHost,
                hostSecondaryName: secondaryHost,
                guestNames: guestNames,
                desiredDurationMinutes: desiredDurationMinutes
            )
            profile = response.profile
            entitlements = response.entitlements
        }
    }

    func saveSchedule(timezone: String, weekdays: [String]) async {
        guard let sessionToken else { return }
        await load {
            let response = try await apiClient.updateSchedule(token: sessionToken, timezone: timezone, weekdays: weekdays)
            schedule = response.schedule
            entitlements = response.entitlements
        }
    }

    private func load(_ operation: () async throws -> Void) async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            try await operation()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
