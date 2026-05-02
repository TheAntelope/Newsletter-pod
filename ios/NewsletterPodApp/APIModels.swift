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
    let maxSources: Int
    let maxDeliveryDays: Int
    let minDurationMinutes: Int
    let maxDurationMinutes: Int
    let maxItemsPerEpisode: Int

    private enum CodingKeys: String, CodingKey {
        case tier
        case maxSources = "max_sources"
        case maxDeliveryDays = "max_delivery_days"
        case minDurationMinutes = "min_duration_minutes"
        case maxDurationMinutes = "max_duration_minutes"
        case maxItemsPerEpisode = "max_items_per_episode"
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

    private enum CodingKeys: String, CodingKey {
        case title
        case formatPreset = "format_preset"
        case hostPrimaryName = "host_primary_name"
        case hostSecondaryName = "host_secondary_name"
        case guestNames = "guest_names"
        case desiredDurationMinutes = "desired_duration_minutes"
        case voiceID = "voice_id"
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
    let durationSeconds: Int?
    let processedItemCount: Int
    let droppedItemCount: Int
    let capHit: Bool

    private enum CodingKeys: String, CodingKey {
        case id
        case title
        case description
        case durationSeconds = "duration_seconds"
        case processedItemCount = "processed_item_count"
        case droppedItemCount = "dropped_item_count"
        case capHit = "cap_hit"
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
