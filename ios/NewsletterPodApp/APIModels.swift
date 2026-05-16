import Foundation

struct SessionEnvelope: Codable {
    let sessionToken: String
    let isNewUser: Bool
    let user: UserDTO
    let subscription: SubscriptionDTO

    private enum CodingKeys: String, CodingKey {
        case sessionToken = "session_token"
        case isNewUser = "is_new_user"
        case user
        case subscription
    }
}

struct MeEnvelope: Codable {
    let user: UserDTO
    let profile: PodcastProfileDTO
    let schedule: DeliveryScheduleDTO
    let subscription: SubscriptionDTO
    let entitlements: EntitlementsDTO
}

struct SourcesEnvelope: Codable {
    let sources: [UserSourceDTO]
    let entitlements: EntitlementsDTO
}

struct CatalogEnvelope: Codable {
    let sources: [CatalogSourceDTO]
}

struct VoiceCatalogEnvelope: Codable {
    let voices: [CatalogVoiceDTO]
}

struct PodcastConfigEnvelope: Codable {
    let profile: PodcastProfileDTO
    let entitlements: EntitlementsDTO
}

struct ScheduleEnvelope: Codable {
    let schedule: DeliveryScheduleDTO
    let entitlements: EntitlementsDTO
}

struct FeedEnvelope: Codable {
    let feedURL: String
    let token: String
    let latestEpisode: UserEpisodeDTO?
    let latestRun: UserRunDTO?
    let subscription: SubscriptionDTO
    let entitlements: EntitlementsDTO

    private enum CodingKeys: String, CodingKey {
        case feedURL = "feed_url"
        case token
        case latestEpisode = "latest_episode"
        case latestRun = "latest_run"
        case subscription
        case entitlements
    }
}

struct UserDTO: Codable {
    let id: String
    let email: String?
    let displayName: String
    let timezone: String
    let inboundAddress: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case email
        case displayName = "display_name"
        case timezone
        case inboundAddress = "inbound_address"
    }

    var hasFriendlyName: Bool {
        let trimmed = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty || trimmed == "Listener" { return false }
        let looksLikeEmailPrefix = !trimmed.contains(" ") &&
            trimmed.range(of: #"^[a-z0-9._-]+$"#, options: .regularExpression) != nil &&
            trimmed.contains(where: { $0.isNumber })
        return !looksLikeEmailPrefix
    }

    var firstName: String {
        guard hasFriendlyName else { return "" }
        let trimmed = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.split(separator: " ").first.map(String.init) ?? trimmed
    }
}

struct SubscriptionDTO: Codable {
    let userID: String
    let tier: String
    let status: String
    let productID: String?

    private enum CodingKeys: String, CodingKey {
        case userID = "user_id"
        case tier
        case status
        case productID = "product_id"
    }
}

struct EntitlementsDTO: Codable {
    let tier: String
    let maxDeliveryDays: Int
    let minDurationMinutes: Int
    let maxDurationMinutes: Int
    let maxItemsPerEpisode: Int

    // Per-week voice-tier quotas (launch tier model). Defaults of 0 keep
    // older clients deserializable if the backend ever omits these fields.
    let premiumPodsPerWeek: Int
    let defaultPodsPerWeek: Int
    let premiumPodsRemainingThisWeek: Int
    let defaultPodsRemainingThisWeek: Int

    let isInTrial: Bool
    let trialPremiumPodsRemaining: Int
    let isInFirstMonth: Bool
    let firstMonthEndsAt: Date?

    private enum CodingKeys: String, CodingKey {
        case tier
        case maxDeliveryDays = "max_delivery_days"
        case minDurationMinutes = "min_duration_minutes"
        case maxDurationMinutes = "max_duration_minutes"
        case maxItemsPerEpisode = "max_items_per_episode"
        case premiumPodsPerWeek = "premium_pods_per_week"
        case defaultPodsPerWeek = "default_pods_per_week"
        case premiumPodsRemainingThisWeek = "premium_pods_remaining_this_week"
        case defaultPodsRemainingThisWeek = "default_pods_remaining_this_week"
        case isInTrial = "is_in_trial"
        case trialPremiumPodsRemaining = "trial_premium_pods_remaining"
        case isInFirstMonth = "is_in_first_month"
        case firstMonthEndsAt = "first_month_ends_at"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        tier = try c.decode(String.self, forKey: .tier)
        maxDeliveryDays = try c.decode(Int.self, forKey: .maxDeliveryDays)
        minDurationMinutes = try c.decode(Int.self, forKey: .minDurationMinutes)
        maxDurationMinutes = try c.decode(Int.self, forKey: .maxDurationMinutes)
        maxItemsPerEpisode = try c.decode(Int.self, forKey: .maxItemsPerEpisode)
        premiumPodsPerWeek = (try? c.decode(Int.self, forKey: .premiumPodsPerWeek)) ?? 0
        defaultPodsPerWeek = (try? c.decode(Int.self, forKey: .defaultPodsPerWeek)) ?? 0
        premiumPodsRemainingThisWeek = (try? c.decode(Int.self, forKey: .premiumPodsRemainingThisWeek)) ?? 0
        defaultPodsRemainingThisWeek = (try? c.decode(Int.self, forKey: .defaultPodsRemainingThisWeek)) ?? 0
        isInTrial = (try? c.decode(Bool.self, forKey: .isInTrial)) ?? false
        trialPremiumPodsRemaining = (try? c.decode(Int.self, forKey: .trialPremiumPodsRemaining)) ?? 0
        isInFirstMonth = (try? c.decode(Bool.self, forKey: .isInFirstMonth)) ?? false
        firstMonthEndsAt = try? c.decodeIfPresent(Date.self, forKey: .firstMonthEndsAt)
    }

    init(
        tier: String,
        maxDeliveryDays: Int,
        minDurationMinutes: Int,
        maxDurationMinutes: Int,
        maxItemsPerEpisode: Int,
        premiumPodsPerWeek: Int = 0,
        defaultPodsPerWeek: Int = 0,
        premiumPodsRemainingThisWeek: Int = 0,
        defaultPodsRemainingThisWeek: Int = 0,
        isInTrial: Bool = false,
        trialPremiumPodsRemaining: Int = 0,
        isInFirstMonth: Bool = false,
        firstMonthEndsAt: Date? = nil
    ) {
        self.tier = tier
        self.maxDeliveryDays = maxDeliveryDays
        self.minDurationMinutes = minDurationMinutes
        self.maxDurationMinutes = maxDurationMinutes
        self.maxItemsPerEpisode = maxItemsPerEpisode
        self.premiumPodsPerWeek = premiumPodsPerWeek
        self.defaultPodsPerWeek = defaultPodsPerWeek
        self.premiumPodsRemainingThisWeek = premiumPodsRemainingThisWeek
        self.defaultPodsRemainingThisWeek = defaultPodsRemainingThisWeek
        self.isInTrial = isInTrial
        self.trialPremiumPodsRemaining = trialPremiumPodsRemaining
        self.isInFirstMonth = isInFirstMonth
        self.firstMonthEndsAt = firstMonthEndsAt
    }
}

struct CatalogSourceDTO: Codable, Identifiable, Hashable {
    let sourceID: String
    let name: String
    let rssURL: String
    let enabled: Bool
    let topic: String?

    var id: String { sourceID }

    private enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case name
        case rssURL = "rss_url"
        case enabled
        case topic
    }
}

struct CatalogVoiceDTO: Codable, Identifiable, Hashable {
    let id: String
    let name: String
    let gender: String
    let description: String
    let previewURL: String?

    private enum CodingKeys: String, CodingKey {
        case id, name, gender, description
        case previewURL = "preview_url"
    }
}

struct UserSourceDTO: Codable, Identifiable, Hashable {
    let id: String
    let sourceID: String
    let name: String
    let rssURL: String
    let isCustom: Bool
    let enabled: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case sourceID = "source_id"
        case name
        case rssURL = "rss_url"
        case isCustom = "is_custom"
        case enabled
    }
}

struct PodcastProfileDTO: Codable {
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

struct DeliveryScheduleDTO: Codable {
    let timezone: String
    let weekdays: [String]
    let localTime: String
    let cutoffTime: String

    private enum CodingKeys: String, CodingKey {
        case timezone
        case weekdays
        case localTime = "local_time"
        case cutoffTime = "cutoff_time"
    }
}

struct UserEpisodeDTO: Codable {
    let id: String
    let title: String
    let description: String
    let publishedAt: Date
    let durationSeconds: Int?
    let processedItemCount: Int
    let droppedItemCount: Int
    let capHit: Bool
    let transcriptText: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case publishedAt = "published_at"
        case durationSeconds = "duration_seconds"
        case processedItemCount = "processed_item_count"
        case droppedItemCount = "dropped_item_count"
        case capHit = "cap_hit"
        case transcriptText = "transcript_text"
    }
}

struct UserRunDTO: Codable {
    let id: String?
    let status: String
    let message: String
    let candidateCount: Int
    let capHit: Bool
    let publishedEpisodeID: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case status
        case message
        case candidateCount = "candidate_count"
        case capHit = "cap_hit"
        case publishedEpisodeID = "published_episode_id"
    }
}

struct RunStartEnvelope: Codable {
    let run: UserRunDTO
    let started: Bool
}

struct InboundItemsEnvelope: Codable {
    let inboundAddress: String?
    let items: [InboundItemDTO]

    private enum CodingKeys: String, CodingKey {
        case inboundAddress = "inbound_address"
        case items
    }
}

struct InboundItemDTO: Codable, Identifiable, Hashable {
    let id: String
    let fromEmail: String
    let fromName: String?
    let senderDomain: String
    let subject: String
    let articleURL: String?
    let receivedAt: Date

    private enum CodingKeys: String, CodingKey {
        case id
        case fromEmail = "from_email"
        case fromName = "from_name"
        case senderDomain = "sender_domain"
        case subject
        case articleURL = "article_url"
        case receivedAt = "received_at"
    }

    var displaySender: String {
        if let name = fromName, !name.isEmpty { return name }
        return senderDomain
    }
}

struct RunStatusEnvelope: Codable {
    let run: UserRunDTO
    let episode: UserEpisodeDTO?
}

struct SubstackProbeDTO: Codable, Hashable {
    let pubURL: String
    let pubHost: String
    let title: String?
    let author: String?
    let iconURL: String?
    let hasPaidTier: Bool
    let feedURL: String

    private enum CodingKeys: String, CodingKey {
        case pubURL = "pub_url"
        case pubHost = "pub_host"
        case title
        case author
        case iconURL = "icon_url"
        case hasPaidTier = "has_paid_tier"
        case feedURL = "feed_url"
    }
}

/// One LLM-suggested + probe-validated Substack candidate from the discovery
/// endpoint. Same shape as `SubstackProbeDTO` plus a one-line `why` reason
/// rendered next to the title.
struct SubstackCandidateDTO: Codable, Hashable, Identifiable {
    let pubURL: String
    let pubHost: String
    let title: String?
    let author: String?
    let iconURL: String?
    let hasPaidTier: Bool
    let feedURL: String
    let why: String?

    var id: String { pubHost }

    private enum CodingKeys: String, CodingKey {
        case pubURL = "pub_url"
        case pubHost = "pub_host"
        case title
        case author
        case iconURL = "icon_url"
        case hasPaidTier = "has_paid_tier"
        case feedURL = "feed_url"
        case why
    }
}

struct SubstackDiscoveryEnvelope: Codable {
    let candidates: [SubstackCandidateDTO]
}

enum SubstackIntentStatus: String, Codable {
    case pending
    case autoConfirmed = "auto_confirmed"
    case confirmed
}

struct SubstackIntentDTO: Codable, Identifiable, Hashable {
    let id: String
    let userID: String
    let pubURL: String
    let pubHost: String
    let pubTitle: String?
    let pubAuthor: String?
    let pubIconURL: String?
    let hasPaidTier: Bool
    let aliasEmail: String
    let createdAt: Date
    let autoConfirmedAt: Date?
    let confirmedAt: Date?
    let status: SubstackIntentStatus

    private enum CodingKeys: String, CodingKey {
        case id
        case userID = "user_id"
        case pubURL = "pub_url"
        case pubHost = "pub_host"
        case pubTitle = "pub_title"
        case pubAuthor = "pub_author"
        case pubIconURL = "pub_icon_url"
        case hasPaidTier = "has_paid_tier"
        case aliasEmail = "alias_email"
        case createdAt = "created_at"
        case autoConfirmedAt = "auto_confirmed_at"
        case confirmedAt = "confirmed_at"
        case status
    }

    /// Display title: the publication title if we have it, otherwise the host.
    var displayTitle: String {
        if let title = pubTitle, !title.isEmpty { return title }
        return pubHost
    }

    /// User-facing status. Per product decision, an intent stays in `.pending`
    /// until a real post arrives (status == .confirmed). The intermediate
    /// `.autoConfirmed` state is internal-only.
    var displayStatus: SubstackIntentStatus {
        status == .confirmed ? .confirmed : .pending
    }

    /// Build the publication's subscribe page URL the deep-link should open.
    var subscribeURL: URL? {
        URL(string: "\(pubURL)/subscribe")
    }
}

struct SubstackIntentsEnvelope: Codable {
    let inboundAddress: String?
    let intents: [SubstackIntentDTO]

    private enum CodingKeys: String, CodingKey {
        case inboundAddress = "inbound_address"
        case intents
    }
}

struct SubstackIntentEnvelope: Codable {
    let intent: SubstackIntentDTO
}

struct EpisodesEnvelope: Codable {
    let episodes: [LibraryEpisodeDTO]
}

struct SourceItemRefDTO: Codable, Hashable, Identifiable {
    let sourceID: String
    let sourceName: String
    let title: String
    let link: String
    let guid: String?

    var id: String { guid ?? link }

    private enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case sourceName = "source_name"
        case title
        case link
        case guid
    }
}

struct LibraryEpisodeDTO: Codable, Identifiable, Hashable {
    let id: String
    let title: String
    let description: String
    let publishedAt: Date
    let durationSeconds: Int?
    let processedItemCount: Int
    let droppedItemCount: Int
    let capHit: Bool
    let sourceItemRefs: [SourceItemRefDTO]
    let transcriptText: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case publishedAt = "published_at"
        case durationSeconds = "duration_seconds"
        case processedItemCount = "processed_item_count"
        case droppedItemCount = "dropped_item_count"
        case capHit = "cap_hit"
        case sourceItemRefs = "source_item_refs"
        case transcriptText = "transcript_text"
    }
}

struct SwipeDeckEnvelope: Codable {
    let items: [SwipeDeckCardDTO]
}

struct SwipeDeckCardDTO: Codable, Identifiable, Equatable {
    let sourceItemDedupeKey: String
    let title: String
    let summary: String
    /// LLM-generated brief summary. When present, the card uses this instead
    /// of the raw `summary` (which is often unstripped HTML or feed boilerplate).
    let cardSummary: String?
    let sourceID: String
    let sourceName: String
    let link: String
    let publishedAt: Date

    var id: String { sourceItemDedupeKey }

    /// Best-available human-readable summary for swipe cards. Prefers the
    /// LLM-generated `cardSummary`; falls back to a cleaned `summary`.
    var displaySummary: String {
        if let card = cardSummary, !card.isEmpty {
            return card
        }
        return SwipeDeckCardDTO.cleanFallback(summary)
    }

    private static func cleanFallback(_ raw: String) -> String {
        // Strip simple HTML tags + collapse whitespace so feed-html summaries
        // are at least readable until the LLM card_summary backfills land.
        let withoutTags = raw.replacingOccurrences(
            of: "<[^>]+>",
            with: " ",
            options: .regularExpression
        )
        let collapsed = withoutTags.replacingOccurrences(
            of: "\\s+",
            with: " ",
            options: .regularExpression
        ).trimmingCharacters(in: .whitespacesAndNewlines)
        if collapsed.count <= 280 { return collapsed }
        let cutoff = collapsed.index(collapsed.startIndex, offsetBy: 280)
        return String(collapsed[..<cutoff]).trimmingCharacters(in: .whitespacesAndNewlines) + "…"
    }

    private enum CodingKeys: String, CodingKey {
        case sourceItemDedupeKey = "source_item_dedupe_key"
        case title
        case summary
        case cardSummary = "card_summary"
        case sourceID = "source_id"
        case sourceName = "source_name"
        case link
        case publishedAt = "published_at"
    }
}
