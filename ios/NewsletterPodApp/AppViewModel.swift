import Foundation

enum DashboardTab: Hashable {
    case home
    case sources
    case podcast
    case feed
    case upgrade
}

@MainActor
final class AppViewModel: ObservableObject {
    static let onboardingCompleteKey = "hasCompletedOnboarding"

    @Published var sessionToken: String?
    @Published var user: UserDTO?
    @Published var profile: PodcastProfileDTO?
    @Published var schedule: DeliveryScheduleDTO?
    @Published var subscription: SubscriptionDTO?
    @Published var entitlements: EntitlementsDTO?
    @Published var catalogSources: [CatalogSourceDTO] = []
    @Published var selectedSources: [UserSourceDTO] = []
    @Published var feed: FeedEnvelope?
    @Published var inboundItems: [InboundItemDTO] = []
    @Published var isLoadingInbound = false
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var savedMessage: String?
    @Published var activeRunID: String?
    @Published var showOnboarding: Bool = false
    @Published var selectedTab: DashboardTab = .home

    let apiClient: APIClient
    let purchaseManager: PurchaseManager
    let isUITestMode: Bool

    private var pollTask: Task<Void, Never>?

    init(apiClient: APIClient = APIClient(), purchaseManager: PurchaseManager = PurchaseManager()) {
        self.apiClient = apiClient
        self.purchaseManager = purchaseManager
        self.isUITestMode = ProcessInfo.processInfo.arguments.contains("-uiTestMode")
        if isUITestMode {
            applyUITestSeed()
        }
    }

    private func applyUITestSeed() {
        UserDefaults.standard.removeObject(forKey: Self.onboardingCompleteKey)
        sessionToken = "ui-test-token"
        user = UserDTO(
            id: "ui-test-user",
            email: nil,
            displayName: "Listener",
            timezone: TimeZone.current.identifier,
            inboundAddress: "uitest@theclawcast.com"
        )
        subscription = SubscriptionDTO(
            userID: "ui-test-user",
            tier: "free",
            status: "active",
            productID: nil
        )
        entitlements = EntitlementsDTO(
            tier: "free",
            maxSources: 5,
            maxDeliveryDays: 7,
            minDurationMinutes: 3,
            maxDurationMinutes: 8,
            maxItemsPerEpisode: 25
        )
        showOnboarding = true
    }

    var isAuthenticated: Bool { sessionToken != nil }
    var isPaid: Bool { subscription?.tier == "paid" }
    var isGenerating: Bool { activeRunID != nil }

    func signIn(identityToken: String, givenName: String? = nil) async {
        await load {
            let session = try await apiClient.signInWithApple(
                identityToken: identityToken,
                givenName: givenName
            )
            sessionToken = session.sessionToken
            user = session.user
            subscription = session.subscription
            try await refresh()
        }
        evaluateOnboardingTrigger()
    }

    func evaluateOnboardingTrigger() {
        guard isAuthenticated else { return }
        if isUITestMode { showOnboarding = true; return }
        if UserDefaults.standard.bool(forKey: Self.onboardingCompleteKey) { return }
        if !selectedSources.isEmpty {
            UserDefaults.standard.set(true, forKey: Self.onboardingCompleteKey)
            return
        }
        showOnboarding = true
    }

    func resumeOnboarding() {
        showOnboarding = true
    }

    func completeOnboarding() {
        UserDefaults.standard.set(true, forKey: Self.onboardingCompleteKey)
        showOnboarding = false
    }

    func refresh() async throws {
        if isUITestMode { return }
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
        resumeGenerationPollingIfNeeded()
    }

    private func resumeGenerationPollingIfNeeded() {
        guard pollTask == nil else { return }
        guard let run = feed?.latestRun, run.status == "in_progress", let runID = run.id else {
            return
        }
        activeRunID = runID
        pollTask = Task { [weak self] in await self?.pollRun(runID: runID) }
    }

    func updateProfile(displayName: String, timezone: String) async {
        guard let sessionToken else { return }
        await load {
            let me = try await apiClient.updateProfile(token: sessionToken, displayName: displayName, timezone: timezone)
            user = me.user
            schedule = me.schedule
            subscription = me.subscription
            entitlements = me.entitlements
            flashSaved("Name saved")
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
            flashSaved("Sources saved")
        }
    }

    func savePodcastConfig(
        title: String,
        formatPreset: String,
        primaryHost: String,
        secondaryHost: String?,
        guestNames: [String],
        desiredDurationMinutes: Int,
        voiceID: String?
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
                desiredDurationMinutes: desiredDurationMinutes,
                voiceID: voiceID
            )
            profile = response.profile
            entitlements = response.entitlements
            flashSaved("Podcast settings saved")
        }
    }

    func generateNow() async {
        guard let sessionToken else { return }
        guard activeRunID == nil else { return }
        do {
            errorMessage = nil
            let envelope = try await apiClient.generateNow(token: sessionToken)
            guard let runID = envelope.run.id else {
                errorMessage = "Could not start generation"
                return
            }
            activeRunID = runID
            pollTask?.cancel()
            pollTask = Task { [weak self] in await self?.pollRun(runID: runID) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func pollRun(runID: String) async {
        defer { pollTask = nil }
        guard let sessionToken else { return }
        let pollInterval: UInt64 = 5_000_000_000
        while !Task.isCancelled {
            do {
                try await Task.sleep(nanoseconds: pollInterval)
            } catch {
                return
            }
            guard activeRunID == runID else { return }
            do {
                let status = try await apiClient.fetchRun(token: sessionToken, runID: runID)
                if status.run.status != "in_progress" {
                    activeRunID = nil
                    try? await refresh()
                    switch status.run.status {
                    case "published":
                        flashSaved("Episode ready")
                    case "no_content":
                        flashSaved("No new items today")
                    case "failed":
                        errorMessage = status.run.message.isEmpty ? "Generation failed" : status.run.message
                    default:
                        break
                    }
                    return
                }
            } catch {
                // Transient poll failure — keep trying.
            }
        }
    }

    func loadInboundItems() async {
        if isUITestMode { return }
        guard let sessionToken else { return }
        isLoadingInbound = true
        defer { isLoadingInbound = false }
        do {
            let envelope = try await apiClient.fetchInboundItems(token: sessionToken)
            inboundItems = envelope.items
        } catch {
            // Non-fatal: leave existing items in place.
        }
    }

    func saveSchedule(timezone: String, weekdays: [String]) async {
        guard let sessionToken else { return }
        await load {
            let response = try await apiClient.updateSchedule(token: sessionToken, timezone: timezone, weekdays: weekdays)
            schedule = response.schedule
            entitlements = response.entitlements
            flashSaved("Schedule saved")
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

    private func flashSaved(_ message: String) {
        savedMessage = message
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_500_000_000)
            if savedMessage == message { savedMessage = nil }
        }
    }
}
