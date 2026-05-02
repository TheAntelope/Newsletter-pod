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
        voiceID: String?
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
                voiceID: voiceID
            ),
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

private struct UpdateScheduleBody: Encodable {
    let timezone: String
    let weekdays: [String]
    let local_time: String?
}
