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
    @Published var catalogVoices: [CatalogVoiceDTO] = []
    @Published var selectedSources: [UserSourceDTO] = []
    @Published var feed: FeedEnvelope?
    @Published var inboundItems: [InboundItemDTO] = []
    @Published var isLoadingInbound = false
    @Published var substackIntents: [SubstackIntentDTO] = []
    @Published var isLoadingSubstackIntents = false
    @Published var libraryEpisodes: [LibraryEpisodeDTO] = []
    @Published var isLoadingEpisodes = false
    @Published var isLoading = false
    @Published var errorMessage: String?
    @Published var savedMessage: String?
    @Published var activeRunID: String?
    @Published var showOnboarding: Bool = false
    @Published var selectedTab: DashboardTab = .home
    /// Last transcript submitted via the onboarding voice intake step. We hold
    /// onto it so the newsletters step can pre-search Substacks based on what
    /// the user just told us, instead of waiting for them to retype it.
    @Published var lastVoiceIntakeTranscript: String?

    let apiClient: APIClient
    let purchaseManager: PurchaseManager
    let isUITestMode: Bool
    /// When -uiTestSkipOnboarding is passed alongside -uiTestMode, the seed
    /// drops the user directly on the dashboard instead of opening the wizard.
    /// Lets capture tests target screens past onboarding without fighting the
    /// force-show logic in `evaluateOnboardingTrigger`.
    let isUITestSkipOnboarding: Bool

    private var pollTask: Task<Void, Never>?

    init(apiClient: APIClient = APIClient(), purchaseManager: PurchaseManager = PurchaseManager()) {
        self.apiClient = apiClient
        self.purchaseManager = purchaseManager
        self.isUITestMode = ProcessInfo.processInfo.arguments.contains("-uiTestMode")
        self.isUITestSkipOnboarding = ProcessInfo.processInfo.arguments.contains("-uiTestSkipOnboarding")
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
            maxDeliveryDays: 7,
            minDurationMinutes: 3,
            maxDurationMinutes: 5,
            maxItemsPerEpisode: 25,
            premiumPodsPerWeek: 5,
            defaultPodsPerWeek: 0,
            premiumPodsRemainingThisWeek: 5,
            defaultPodsRemainingThisWeek: 0,
            isInTrial: true,
            trialPremiumPodsRemaining: 5,
            isInFirstMonth: false,
            firstMonthEndsAt: nil
        )
        // Seed a representative profile + schedule so the Podcast Setup tab
        // renders populated UI in screenshot tests (3/4/5-min duration picker
        // selection, weather location row, etc.). Onboarding tests still see
        // the wizard because showOnboarding is forced true below.
        profile = PodcastProfileDTO(
            title: "ClawCast",
            formatPreset: "two_hosts",
            hostPrimaryName: "Vinnie",
            hostSecondaryName: "Demi",
            guestNames: [],
            desiredDurationMinutes: 4,
            voiceID: nil,
            secondaryVoiceID: nil,
            tone: "calm_analyst",
            keyFindingsCount: 3,
            humorStyle: "none",
            personalizedGreeting: true,
            includeTopTakeaways: true,
            includeWeather: true,
            weatherLocation: "Copenhagen, Denmark",
            customGuidance: nil,
            customGuidancePresetID: nil
        )
        schedule = DeliveryScheduleDTO(
            timezone: TimeZone.current.identifier,
            weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
            localTime: "07:00",
            cutoffTime: "06:00"
        )
        showOnboarding = !isUITestSkipOnboarding
    }

    var isAuthenticated: Bool { sessionToken != nil }
    /// Backwards-compatible "user has any paid subscription" flag. True for
    /// pro, max, or legacy paid rows; false for free.
    var isPaid: Bool {
        let tier = subscription?.tier ?? "free"
        return tier == "pro" || tier == "max" || tier == "paid"
    }
    var isPro: Bool { subscription?.tier == "pro" || subscription?.tier == "paid" }
    var isMax: Bool { subscription?.tier == "max" }
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
        if isUITestMode {
            if isUITestSkipOnboarding { return }
            showOnboarding = true
            return
        }
        // Backend truth wins. If the server says the user has sources, mark
        // local onboarding done and stay out. If the server says no sources,
        // re-show the wizard regardless of the local flag — that covers both
        // a fresh install and a server-side profile reset (which used to
        // require deleting and reinstalling the app to clear UserDefaults).
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
        async let voices = apiClient.fetchVoiceCatalog()
        async let sources = apiClient.fetchSources(token: sessionToken)
        async let feed = apiClient.fetchFeed(token: sessionToken)

        let meValue = try await me
        let catalogValue = try await catalog
        let voicesValue = try await voices
        let sourcesValue = try await sources
        let feedValue = try await feed

        user = meValue.user
        profile = meValue.profile
        schedule = meValue.schedule
        subscription = meValue.subscription
        entitlements = meValue.entitlements
        catalogSources = catalogValue.sources
        catalogVoices = voicesValue.voices
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
        }
    }

    func savePodcastConfig(
        title: String,
        formatPreset: String,
        primaryHost: String,
        secondaryHost: String?,
        guestNames: [String],
        desiredDurationMinutes: Int,
        voiceID: String?,
        secondaryVoiceID: String? = nil,
        tone: String? = nil,
        keyFindingsCount: Int? = nil,
        humorStyle: String? = nil,
        personalizedGreeting: Bool? = nil,
        includeTopTakeaways: Bool? = nil,
        includeWeather: Bool? = nil,
        weatherLocation: String? = nil,
        customGuidance: String? = nil,
        customGuidancePresetID: String? = nil
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
                voiceID: voiceID,
                secondaryVoiceID: secondaryVoiceID,
                tone: tone,
                keyFindingsCount: keyFindingsCount,
                humorStyle: humorStyle,
                personalizedGreeting: personalizedGreeting,
                includeTopTakeaways: includeTopTakeaways,
                includeWeather: includeWeather,
                weatherLocation: weatherLocation,
                customGuidance: customGuidance,
                customGuidancePresetID: customGuidancePresetID
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

    func loadSubstackIntents() async {
        if isUITestMode { return }
        guard let sessionToken else { return }
        isLoadingSubstackIntents = true
        defer { isLoadingSubstackIntents = false }
        do {
            let envelope = try await apiClient.fetchSubstackIntents(token: sessionToken)
            substackIntents = envelope.intents
        } catch {
            // Non-fatal: leave existing intents in place.
        }
    }

    /// Probe a user-typed Substack URL. Returns the preview metadata for the
    /// AddSubstackSheet's preview card, or nil if the probe failed (caller
    /// can read `errorMessage` for the reason).
    func probeSubstack(url: String) async -> SubstackProbeDTO? {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        do {
            errorMessage = nil
            return try await apiClient.probeSubstack(url: trimmed)
        } catch let APIError.server(message) {
            errorMessage = message
            return nil
        } catch {
            errorMessage = "Could not reach that Substack — double-check the URL."
            return nil
        }
    }

    /// Create (or fetch existing) intent for a publication. Returns the
    /// intent so the caller can deep-link to its subscribe page.
    func createSubstackIntent(pubURL: String) async -> SubstackIntentDTO? {
        guard let sessionToken else { return nil }
        do {
            errorMessage = nil
            let envelope = try await apiClient.createSubstackIntent(token: sessionToken, pubURL: pubURL)
            // Refresh the in-memory list so the new intent shows up
            // immediately on the Sources page.
            if !substackIntents.contains(where: { $0.id == envelope.intent.id }) {
                substackIntents.insert(envelope.intent, at: 0)
            } else {
                substackIntents = substackIntents.map { existing in
                    existing.id == envelope.intent.id ? envelope.intent : existing
                }
            }
            return envelope.intent
        } catch let APIError.server(message) {
            errorMessage = message
            return nil
        } catch {
            errorMessage = "Could not add that Substack — try again."
            return nil
        }
    }

    func deleteSubstackIntent(_ intent: SubstackIntentDTO) async {
        guard let sessionToken else { return }
        // Optimistic remove so the row disappears immediately. On failure
        // we leave the error toast up; the user can reload to recover.
        let before = substackIntents
        substackIntents.removeAll { $0.id == intent.id }
        do {
            try await apiClient.deleteSubstackIntent(token: sessionToken, intentID: intent.id)
        } catch let APIError.server(message) {
            errorMessage = message
            substackIntents = before
        } catch {
            errorMessage = "Could not remove that subscription."
            substackIntents = before
        }
    }

    func loadEpisodes() async {
        if isUITestMode { return }
        guard let sessionToken else { return }
        isLoadingEpisodes = true
        defer { isLoadingEpisodes = false }
        do {
            let envelope = try await apiClient.fetchEpisodes(token: sessionToken)
            libraryEpisodes = envelope.episodes
        } catch {
            // Non-fatal: leave existing items in place.
        }
    }

    func submitFeedback(text: String, source: String) async -> Bool {
        guard let sessionToken else { return false }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        let locale = Locale.current.identifier
        do {
            errorMessage = nil
            try await apiClient.submitFeedback(
                token: sessionToken,
                text: trimmed,
                localeHint: locale,
                source: source
            )
            flashSaved("Feedback sent")
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func fetchRecentSwipeDeck() async -> [SwipeDeckCardDTO] {
        guard let sessionToken else { return [] }
        do {
            let envelope = try await apiClient.fetchRecentSwipeDeck(token: sessionToken)
            return envelope.items
        } catch {
            errorMessage = error.localizedDescription
            return []
        }
    }

    func fetchColdStartSwipeDeck() async -> [SwipeDeckCardDTO] {
        guard let sessionToken else { return [] }
        do {
            let envelope = try await apiClient.fetchColdStartSwipeDeck(token: sessionToken)
            return envelope.items
        } catch {
            errorMessage = error.localizedDescription
            return []
        }
    }

    func submitVoiceIntake(transcript: String) async -> VoiceIntakeAck? {
        guard let sessionToken else { return nil }
        do {
            let ack = try await apiClient.submitVoiceIntake(
                token: sessionToken,
                transcript: transcript
            )
            lastVoiceIntakeTranscript = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
            return ack
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    /// Deletes the user's account and all associated data on the backend,
    /// then clears every piece of per-user state we hold locally so the app
    /// snaps back to the Sign-in screen. Returns true on success.
    func deleteAccount() async -> Bool {
        guard let sessionToken else { return false }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            _ = try await apiClient.deleteAccount(token: sessionToken)
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
        pollTask?.cancel()
        pollTask = nil
        self.sessionToken = nil
        user = nil
        profile = nil
        schedule = nil
        subscription = nil
        entitlements = nil
        selectedSources = []
        feed = nil
        inboundItems = []
        substackIntents = []
        libraryEpisodes = []
        activeRunID = nil
        showOnboarding = false
        selectedTab = .home
        UserDefaults.standard.removeObject(forKey: Self.onboardingCompleteKey)
        flashSaved("Account deleted")
        return true
    }

    /// Wipes the user's onboarding state on the backend (sources, schedule,
    /// podcast profile, swipes, substack intents, per-source cursors) and
    /// re-shows the onboarding wizard. Keeps the session, feed token,
    /// subscription, and episode history. Returns true on success.
    func resetAlgorithm() async -> Bool {
        guard let sessionToken else { return false }
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            _ = try await apiClient.resetAlgorithm(token: sessionToken)
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
        pollTask?.cancel()
        pollTask = nil
        profile = nil
        schedule = nil
        selectedSources = []
        substackIntents = []
        activeRunID = nil
        UserDefaults.standard.removeObject(forKey: Self.onboardingCompleteKey)
        showOnboarding = true
        selectedTab = .home
        flashSaved("Algorithm reset")
        return true
    }

    func discoverSubstacks(query: String) async -> [SubstackCandidateDTO] {
        guard let sessionToken else { return [] }
        do {
            errorMessage = nil
            let envelope = try await apiClient.discoverSubstacks(token: sessionToken, query: query)
            return envelope.candidates
        } catch {
            errorMessage = error.localizedDescription
            return []
        }
    }

    func submitSwipe(card: SwipeDeckCardDTO, direction: Int) async {
        guard let sessionToken else { return }
        do {
            try await apiClient.submitSwipe(
                token: sessionToken,
                dedupeKey: card.sourceItemDedupeKey,
                direction: direction
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @Published var isRefreshingCorpus: Bool = false

    func refreshCorpus() async -> Bool {
        guard let sessionToken else { return false }
        isRefreshingCorpus = true
        defer { isRefreshingCorpus = false }
        do {
            _ = try await apiClient.refreshCorpus(token: sessionToken)
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func saveSchedule(timezone: String, weekdays: [String], localTime: String? = nil) async {
        guard let sessionToken else { return }
        await load {
            let response = try await apiClient.updateSchedule(
                token: sessionToken,
                timezone: timezone,
                weekdays: weekdays,
                localTime: localTime
            )
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
