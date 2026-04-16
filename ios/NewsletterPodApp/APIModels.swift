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

    private enum CodingKeys: String, CodingKey {
        case id
        case email
        case displayName = "display_name"
        case timezone
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

    var id: String { sourceID }

    private enum CodingKeys: String, CodingKey {
        case sourceID = "source_id"
        case name
        case rssURL = "rss_url"
        case enabled
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

    private enum CodingKeys: String, CodingKey {
        case title
        case formatPreset = "format_preset"
        case hostPrimaryName = "host_primary_name"
        case hostSecondaryName = "host_secondary_name"
        case guestNames = "guest_names"
        case desiredDurationMinutes = "desired_duration_minutes"
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
    let status: String
    let message: String
    let candidateCount: Int
    let capHit: Bool

    private enum CodingKeys: String, CodingKey {
        case status
        case message
        case candidateCount = "candidate_count"
        case capHit = "cap_hit"
    }
}
