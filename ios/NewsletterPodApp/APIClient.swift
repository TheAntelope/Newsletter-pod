import Foundation

enum APIError: Error, LocalizedError {
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid server response."
        case .server(let message):
            return message
        }
    }
}

final class APIClient {
    private let baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL = AppConfiguration.baseURL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
        self.decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let value = try container.decode(String.self)
            if let date = APIClient.iso8601WithFractional.date(from: value) {
                return date
            }
            if let date = APIClient.iso8601Plain.date(from: value) {
                return date
            }
            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Could not parse date: \(value)"
            )
        }
        self.encoder.dateEncodingStrategy = .iso8601
    }

    private static let iso8601WithFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let iso8601Plain: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    func signInWithApple(identityToken: String, givenName: String? = nil) async throws -> SessionEnvelope {
        try await request(
            path: "/v1/auth/apple",
            method: "POST",
            body: AppleAuthBody(identityToken: identityToken, givenName: givenName),
            token: nil
        )
    }

    func fetchMe(token: String) async throws -> MeEnvelope {
        try await request(path: "/v1/me", method: "GET", body: Optional<Int>.none, token: token)
    }

    func updateProfile(token: String, displayName: String, timezone: String) async throws -> MeEnvelope {
        try await request(
            path: "/v1/me",
            method: "PATCH",
            body: UpdateProfileBody(displayName: displayName, timezone: timezone),
            token: token
        )
    }

    func fetchCatalog() async throws -> CatalogEnvelope {
        try await request(path: "/v1/sources/catalog", method: "GET", body: Optional<Int>.none, token: nil)
    }

    func fetchVoiceCatalog() async throws -> VoiceCatalogEnvelope {
        try await request(path: "/v1/voices/catalog", method: "GET", body: Optional<Int>.none, token: nil)
    }

    func fetchSources(token: String) async throws -> SourcesEnvelope {
        try await request(path: "/v1/me/sources", method: "GET", body: Optional<Int>.none, token: token)
    }

    func replaceSources(token: String, sources: [SourcePayload]) async throws -> SourcesEnvelope {
        try await request(
            path: "/v1/me/sources",
            method: "PUT",
            body: ReplaceSourcesBody(sources: sources),
            token: token
        )
    }

    func fetchPodcastConfig(token: String) async throws -> PodcastConfigEnvelope {
        try await request(path: "/v1/me/podcast-config", method: "GET", body: Optional<Int>.none, token: token)
    }

    func updatePodcastConfig(
        token: String,
        title: String,
        formatPreset: String,
        hostPrimaryName: String,
        hostSecondaryName: String?,
        guestNames: [String],
        desiredDurationMinutes: Int,
        voiceID: String?,
        secondaryVoiceID: String?,
        tone: String? = nil,
        keyFindingsCount: Int? = nil,
        humorStyle: String? = nil,
        personalizedGreeting: Bool? = nil,
        includeTopTakeaways: Bool? = nil,
        includeWeather: Bool? = nil,
        weatherLocation: String? = nil,
        customGuidance: String? = nil,
        customGuidancePresetID: String? = nil
    ) async throws -> PodcastConfigEnvelope {
        try await request(
            path: "/v1/me/podcast-config",
            method: "PATCH",
            body: UpdatePodcastConfigBody(
                title: title,
                formatPreset: formatPreset,
                hostPrimaryName: hostPrimaryName,
                hostSecondaryName: hostSecondaryName,
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
            ),
            token: token
        )
    }

    func submitFeedback(
        token: String,
        text: String,
        localeHint: String?,
        source: String
    ) async throws {
        let _: FeedbackAck = try await request(
            path: "/v1/me/feedback",
            method: "POST",
            body: SubmitFeedbackBody(text: text, localeHint: localeHint, source: source),
            token: token
        )
    }

    func fetchSchedule(token: String) async throws -> ScheduleEnvelope {
        try await request(path: "/v1/me/schedule", method: "GET", body: Optional<Int>.none, token: token)
    }

    func updateSchedule(token: String, timezone: String, weekdays: [String], localTime: String?) async throws -> ScheduleEnvelope {
        try await request(
            path: "/v1/me/schedule",
            method: "PATCH",
            body: UpdateScheduleBody(timezone: timezone, weekdays: weekdays, local_time: localTime),
            token: token
        )
    }

    func fetchFeed(token: String) async throws -> FeedEnvelope {
        try await request(path: "/v1/me/feed", method: "GET", body: Optional<Int>.none, token: token)
    }

    func fetchInboundItems(token: String) async throws -> InboundItemsEnvelope {
        try await request(path: "/v1/me/inbound-items", method: "GET", body: Optional<Int>.none, token: token)
    }

    func fetchEpisodes(token: String) async throws -> EpisodesEnvelope {
        try await request(path: "/v1/me/episodes", method: "GET", body: Optional<Int>.none, token: token)
    }

    func generateNow(token: String) async throws -> RunStartEnvelope {
        try await request(path: "/v1/me/generate", method: "POST", body: Optional<Int>.none, token: token)
    }

    func fetchRun(token: String, runID: String) async throws -> RunStatusEnvelope {
        try await request(path: "/v1/me/runs/\(runID)", method: "GET", body: Optional<Int>.none, token: token)
    }

    func fetchRecentSwipeDeck(token: String) async throws -> SwipeDeckEnvelope {
        try await request(path: "/v1/me/swipe-deck/recent", method: "GET", body: Optional<Int>.none, token: token)
    }

    func fetchColdStartSwipeDeck(token: String) async throws -> SwipeDeckEnvelope {
        try await request(path: "/v1/me/swipe-deck/cold-start", method: "GET", body: Optional<Int>.none, token: token)
    }

    func submitSwipe(token: String, dedupeKey: String, direction: Int) async throws {
        let _: SwipeAck = try await request(
            path: "/v1/me/swipes",
            method: "POST",
            body: SubmitSwipeBody(sourceItemDedupeKey: dedupeKey, direction: direction),
            token: token
        )
    }

    func fetchNextEpisodeQueue(token: String) async throws -> NextEpisodeQueueEnvelope {
        try await request(
            path: "/v1/me/next-episode/candidates",
            method: "GET",
            body: Optional<Int>.none,
            token: token
        )
    }

    func pinNextEpisodeItem(token: String, dedupeKey: String) async throws {
        let _: NextEpisodeOverrideAck = try await request(
            path: "/v1/me/next-episode/pin",
            method: "POST",
            body: NextEpisodeOverrideBody(sourceItemDedupeKey: dedupeKey),
            token: token
        )
    }

    func excludeNextEpisodeItem(token: String, dedupeKey: String) async throws {
        let _: NextEpisodeOverrideAck = try await request(
            path: "/v1/me/next-episode/exclude",
            method: "POST",
            body: NextEpisodeOverrideBody(sourceItemDedupeKey: dedupeKey),
            token: token
        )
    }

    func clearNextEpisodeOverride(token: String, dedupeKey: String) async throws {
        // DELETE with query string — see backend route note.
        guard var components = URLComponents(string: "/v1/me/next-episode/override") else {
            throw APIError.invalidResponse
        }
        components.queryItems = [
            URLQueryItem(name: "source_item_dedupe_key", value: dedupeKey)
        ]
        let path = components.string ?? "/v1/me/next-episode/override"
        let _: NextEpisodeOverrideAck = try await request(
            path: path, method: "DELETE", body: Optional<Int>.none, token: token
        )
    }

    func submitVoiceIntake(token: String, transcript: String) async throws -> VoiceIntakeAck {
        try await request(
            path: "/v1/me/voice-intake",
            method: "POST",
            body: VoiceIntakeBody(transcript: transcript),
            token: token
        )
    }

    func refreshCorpus(token: String) async throws -> CorpusRefreshAck {
        try await request(
            path: "/v1/me/corpus/refresh",
            method: "POST",
            body: Optional<Int>.none,
            token: token
        )
    }

    func discoverSubstacks(token: String, query: String) async throws -> SubstackDiscoveryEnvelope {
        try await request(
            path: "/v1/substack/discover",
            method: "POST",
            body: DiscoverSubstacksBody(query: query),
            token: token
        )
    }

    func probeSubstack(url: String) async throws -> SubstackProbeDTO {
        guard var components = URLComponents(string: "/v1/substack/probe") else {
            throw APIError.invalidResponse
        }
        components.queryItems = [URLQueryItem(name: "url", value: url)]
        let path = components.string ?? "/v1/substack/probe"
        return try await request(path: path, method: "GET", body: Optional<Int>.none, token: nil)
    }

    func fetchSubstackIntents(token: String) async throws -> SubstackIntentsEnvelope {
        try await request(path: "/v1/me/substack/intents", method: "GET", body: Optional<Int>.none, token: token)
    }

    func createSubstackIntent(token: String, pubURL: String) async throws -> SubstackIntentEnvelope {
        try await request(
            path: "/v1/me/substack/intents",
            method: "POST",
            body: CreateSubstackIntentBody(pubURL: pubURL),
            token: token
        )
    }

    func deleteSubstackIntent(token: String, intentID: String) async throws {
        let _: SubstackDeleteAck = try await request(
            path: "/v1/me/substack/intents/\(intentID)",
            method: "DELETE",
            body: Optional<Int>.none,
            token: token
        )
    }

    /// Registers (or refreshes) an APNs device token on the user's account.
    /// Backend dedupes on (user_id, token) so calling this on every cold
    /// start is safe — it just bumps `last_seen_at`.
    func registerDeviceToken(
        token: String,
        deviceToken: String,
        environment: String,
        bundleID: String
    ) async throws -> DeviceTokenAck {
        try await request(
            path: "/v1/me/device-tokens",
            method: "POST",
            body: RegisterDeviceTokenBody(
                token: deviceToken,
                environment: environment,
                bundleID: bundleID
            ),
            token: token
        )
    }

    func deleteAccount(token: String) async throws -> AccountDeletionAck {
        try await request(
            path: "/v1/me",
            method: "DELETE",
            body: Optional<Int>.none,
            token: token
        )
    }

    func resetAlgorithm(token: String) async throws -> AccountResetAck {
        try await request(
            path: "/v1/me/reset",
            method: "POST",
            body: Optional<Int>.none,
            token: token
        )
    }

    func verifySubscription(token: String, signedTransactionInfo: String) async throws -> VerifySubscriptionEnvelope {
        try await request(
            path: "/v1/me/subscription/verify",
            method: "POST",
            body: VerifySubscriptionBody(signedTransactionInfo: signedTransactionInfo),
            token: token
        )
    }

    private func request<T: Decodable, Body: Encodable>(
        path: String,
        method: String,
        body: Body?,
        token: String?
    ) async throws -> T {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw APIError.invalidResponse
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.httpBody = try encoder.encode(body)
        }

        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200..<300).contains(httpResponse.statusCode) else {
            if let message = try? decoder.decode(ServerErrorEnvelope.self, from: data) {
                throw APIError.server(message.detail)
            }
            throw APIError.server("Request failed with status \(httpResponse.statusCode)")
        }

        return try decoder.decode(T.self, from: data)
    }
}

private struct ServerErrorEnvelope: Decodable {
    let detail: String
}

private struct FeedbackAck: Decodable {
    let id: String
}

private struct VerifySubscriptionBody: Encodable {
    let signedTransactionInfo: String

    private enum CodingKeys: String, CodingKey {
        case signedTransactionInfo = "signed_transaction_info"
    }
}

struct VerifySubscriptionEnvelope: Decodable {
    let accepted: Bool
    let eventID: String?
    let subscription: SubscriptionPayload?

    struct SubscriptionPayload: Decodable {
        let tier: String
        let status: String?
        let productID: String?
        let expiresAt: String?

        private enum CodingKeys: String, CodingKey {
            case tier
            case status
            case productID = "product_id"
            case expiresAt = "expires_at"
        }
    }

    private enum CodingKeys: String, CodingKey {
        case accepted
        case eventID = "event_id"
        case subscription
    }
}

private struct SubmitFeedbackBody: Encodable {
    let text: String
    let localeHint: String?
    let source: String

    private enum CodingKeys: String, CodingKey {
        case text
        case localeHint = "locale_hint"
        case source
    }
}

private struct AppleAuthBody: Encodable {
    let identityToken: String
    let givenName: String?

    private enum CodingKeys: String, CodingKey {
        case identityToken = "identity_token"
        case givenName = "given_name"
    }
}

private struct UpdateProfileBody: Encodable {
    let displayName: String
    let timezone: String

    private enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case timezone
    }
}

private struct ReplaceSourcesBody: Encodable {
    let sources: [SourcePayload]
}

struct SourcePayload: Encodable {
    let sourceID: String?
    let rssURL: String?
    let isCustom: Bool?

    private enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case rssURL = "rss_url"
        case isCustom = "is_custom"
    }
}

private struct UpdatePodcastConfigBody: Encodable {
    let title: String
    let formatPreset: String
    let hostPrimaryName: String
    let hostSecondaryName: String?
    let guestNames: [String]
    let desiredDurationMinutes: Int
    let voiceID: String?
    let secondaryVoiceID: String?
    let tone: String?
    let keyFindingsCount: Int?
    let humorStyle: String?
    let personalizedGreeting: Bool?
    let includeTopTakeaways: Bool?
    let includeWeather: Bool?
    let weatherLocation: String?
    let customGuidance: String?
    let customGuidancePresetID: String?

    private enum CodingKeys: String, CodingKey {
        case title
        case formatPreset = "format_preset"
        case hostPrimaryName = "host_primary_name"
        case hostSecondaryName = "host_secondary_name"
        case guestNames = "guest_names"
        case desiredDurationMinutes = "desired_duration_minutes"
        case voiceID = "voice_id"
        case secondaryVoiceID = "secondary_voice_id"
        case tone
        case keyFindingsCount = "key_findings_count"
        case humorStyle = "humor_style"
        case personalizedGreeting = "personalized_greeting"
        case includeTopTakeaways = "include_top_takeaways"
        case includeWeather = "include_weather"
        case weatherLocation = "weather_location"
        case customGuidance = "custom_guidance"
        case customGuidancePresetID = "custom_guidance_preset_id"
    }
}

private struct UpdateScheduleBody: Encodable {
    let timezone: String
    let weekdays: [String]
    let local_time: String?
}

private struct SubmitSwipeBody: Encodable {
    let sourceItemDedupeKey: String
    let direction: Int

    private enum CodingKeys: String, CodingKey {
        case sourceItemDedupeKey = "source_item_dedupe_key"
        case direction
    }
}

private struct SwipeAck: Decodable {
    let id: String
}

private struct NextEpisodeOverrideBody: Encodable {
    let sourceItemDedupeKey: String

    private enum CodingKeys: String, CodingKey {
        case sourceItemDedupeKey = "source_item_dedupe_key"
    }
}

private struct NextEpisodeOverrideAck: Decodable {
    // The backend returns {status, dedupe_key, pins_remaining?} — we don't
    // need the fields client-side beyond confirming the call succeeded,
    // but Decodable requires at least one decode for any present field.
    let status: String?
}

struct CorpusRefreshAck: Decodable {
    let sourcesProcessed: Int
    let itemsIngested: Int

    private enum CodingKeys: String, CodingKey {
        case sourcesProcessed = "sources_processed"
        case itemsIngested = "items_ingested"
    }
}

private struct CreateSubstackIntentBody: Encodable {
    let pubURL: String

    private enum CodingKeys: String, CodingKey {
        case pubURL = "pub_url"
    }
}

private struct RegisterDeviceTokenBody: Encodable {
    let token: String
    let environment: String
    let bundleID: String

    private enum CodingKeys: String, CodingKey {
        case token
        case environment
        case bundleID = "bundle_id"
    }
}

struct DeviceTokenAck: Decodable {
    let tokenID: String
    let status: String

    private enum CodingKeys: String, CodingKey {
        case tokenID = "token_id"
        case status
    }
}

private struct DiscoverSubstacksBody: Encodable {
    let query: String
}

private struct SubstackDeleteAck: Decodable {
    let deleted: Bool
}

private struct VoiceIntakeBody: Encodable {
    let transcript: String
}

struct VoiceIntakeAck: Decodable {
    let seededCount: Int
    let topics: [String]
    let namedEntities: [String]
    let anchorPhrases: [String]
    let vibeNotes: String?

    private enum CodingKeys: String, CodingKey {
        case seededCount = "seeded_count"
        case topics
        case namedEntities = "named_entities"
        case anchorPhrases = "anchor_phrases"
        case vibeNotes = "vibe_notes"
    }
}

struct AccountDeletionAck: Decodable {
    let userID: String
    let alreadyDeleted: Bool
    let audioObjectsDeleted: Int

    private enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case alreadyDeleted = "already_deleted"
        case audioObjectsDeleted = "audio_objects_deleted"
    }
}

struct AccountResetAck: Decodable {
    let userID: String

    private enum CodingKeys: String, CodingKey {
        case userID = "user_id"
    }
}
