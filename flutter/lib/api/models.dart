// Dart port of ios/NewsletterPodApp/APIModels.swift — the backend DTOs.
// JSON keys are snake_case; FieldRename.snake maps them to camelCase fields.
// (de)serialization is generated into models.g.dart by json_serializable.
import 'package:json_annotation/json_annotation.dart';

part 'models.g.dart';

// ---------------------------------------------------------------------------
// Envelopes
// ---------------------------------------------------------------------------

@JsonSerializable(fieldRename: FieldRename.snake)
class SessionEnvelope {
  final String sessionToken;
  final bool isNewUser;
  final UserDto user;
  final SubscriptionDto subscription;

  SessionEnvelope({
    required this.sessionToken,
    required this.isNewUser,
    required this.user,
    required this.subscription,
  });

  factory SessionEnvelope.fromJson(Map<String, dynamic> json) =>
      _$SessionEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$SessionEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class MeEnvelope {
  final UserDto user;
  final PodcastProfileDto profile;
  final DeliveryScheduleDto schedule;
  final SubscriptionDto subscription;
  final EntitlementsDto entitlements;

  MeEnvelope({
    required this.user,
    required this.profile,
    required this.schedule,
    required this.subscription,
    required this.entitlements,
  });

  factory MeEnvelope.fromJson(Map<String, dynamic> json) =>
      _$MeEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$MeEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SourcesEnvelope {
  final List<UserSourceDto> sources;
  final EntitlementsDto entitlements;

  SourcesEnvelope({required this.sources, required this.entitlements});

  factory SourcesEnvelope.fromJson(Map<String, dynamic> json) =>
      _$SourcesEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$SourcesEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class CatalogEnvelope {
  final List<CatalogSourceDto> sources;

  CatalogEnvelope({required this.sources});

  factory CatalogEnvelope.fromJson(Map<String, dynamic> json) =>
      _$CatalogEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$CatalogEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class VoiceCatalogEnvelope {
  final List<CatalogVoiceDto> voices;

  VoiceCatalogEnvelope({required this.voices});

  factory VoiceCatalogEnvelope.fromJson(Map<String, dynamic> json) =>
      _$VoiceCatalogEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$VoiceCatalogEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class PodcastConfigEnvelope {
  final PodcastProfileDto profile;
  final EntitlementsDto entitlements;

  PodcastConfigEnvelope({required this.profile, required this.entitlements});

  factory PodcastConfigEnvelope.fromJson(Map<String, dynamic> json) =>
      _$PodcastConfigEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$PodcastConfigEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class ScheduleEnvelope {
  final DeliveryScheduleDto schedule;
  final EntitlementsDto entitlements;

  ScheduleEnvelope({required this.schedule, required this.entitlements});

  factory ScheduleEnvelope.fromJson(Map<String, dynamic> json) =>
      _$ScheduleEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$ScheduleEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class FeedEnvelope {
  final String feedUrl;
  final String token;
  final UserEpisodeDto? latestEpisode;
  final UserRunDto? latestRun;
  final SubscriptionDto subscription;
  final EntitlementsDto entitlements;

  FeedEnvelope({
    required this.feedUrl,
    required this.token,
    this.latestEpisode,
    this.latestRun,
    required this.subscription,
    required this.entitlements,
  });

  factory FeedEnvelope.fromJson(Map<String, dynamic> json) =>
      _$FeedEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$FeedEnvelopeToJson(this);
}

// ---------------------------------------------------------------------------
// Core DTOs
// ---------------------------------------------------------------------------

@JsonSerializable(fieldRename: FieldRename.snake)
class UserDto {
  final String id;
  final String? email;
  final String displayName;
  final String timezone;
  final String? inboundAddress;

  UserDto({
    required this.id,
    this.email,
    required this.displayName,
    required this.timezone,
    this.inboundAddress,
  });

  factory UserDto.fromJson(Map<String, dynamic> json) =>
      _$UserDtoFromJson(json);
  Map<String, dynamic> toJson() => _$UserDtoToJson(this);

  bool get hasFriendlyName {
    final trimmed = displayName.trim();
    if (trimmed.isEmpty || trimmed == 'Listener') return false;
    final looksLikeEmailPrefix = !trimmed.contains(' ') &&
        RegExp(r'^[a-z0-9._-]+$').hasMatch(trimmed) &&
        trimmed.contains(RegExp(r'[0-9]'));
    return !looksLikeEmailPrefix;
  }

  String get firstName {
    if (!hasFriendlyName) return '';
    final trimmed = displayName.trim();
    final parts = trimmed.split(' ');
    return parts.isNotEmpty ? parts.first : trimmed;
  }
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SubscriptionDto {
  final String userId;
  final String tier;
  final String status;
  final String? productId;

  SubscriptionDto({
    required this.userId,
    required this.tier,
    required this.status,
    this.productId,
  });

  factory SubscriptionDto.fromJson(Map<String, dynamic> json) =>
      _$SubscriptionDtoFromJson(json);
  Map<String, dynamic> toJson() => _$SubscriptionDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class EntitlementsDto {
  final String tier;
  final int maxDeliveryDays;
  final int minDurationMinutes;
  final int maxDurationMinutes;
  final int maxItemsPerEpisode;

  // Per-week voice-tier quotas. Defaults keep older payloads deserializable.
  @JsonKey(defaultValue: 0)
  final int premiumPodsPerWeek;
  @JsonKey(defaultValue: 0)
  final int defaultPodsPerWeek;
  @JsonKey(defaultValue: 0)
  final int premiumPodsRemainingThisWeek;
  @JsonKey(defaultValue: 0)
  final int defaultPodsRemainingThisWeek;
  @JsonKey(defaultValue: false)
  final bool isInTrial;
  @JsonKey(defaultValue: 0)
  final int trialPremiumPodsRemaining;
  @JsonKey(defaultValue: false)
  final bool isInFirstMonth;
  final DateTime? firstMonthEndsAt;

  EntitlementsDto({
    required this.tier,
    required this.maxDeliveryDays,
    required this.minDurationMinutes,
    required this.maxDurationMinutes,
    required this.maxItemsPerEpisode,
    this.premiumPodsPerWeek = 0,
    this.defaultPodsPerWeek = 0,
    this.premiumPodsRemainingThisWeek = 0,
    this.defaultPodsRemainingThisWeek = 0,
    this.isInTrial = false,
    this.trialPremiumPodsRemaining = 0,
    this.isInFirstMonth = false,
    this.firstMonthEndsAt,
  });

  factory EntitlementsDto.fromJson(Map<String, dynamic> json) =>
      _$EntitlementsDtoFromJson(json);
  Map<String, dynamic> toJson() => _$EntitlementsDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class CatalogSourceDto {
  final String sourceId;
  final String name;
  final String rssUrl;
  final bool enabled;
  final String? topic;

  CatalogSourceDto({
    required this.sourceId,
    required this.name,
    required this.rssUrl,
    required this.enabled,
    this.topic,
  });

  factory CatalogSourceDto.fromJson(Map<String, dynamic> json) =>
      _$CatalogSourceDtoFromJson(json);
  Map<String, dynamic> toJson() => _$CatalogSourceDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class CatalogVoiceDto {
  final String id;
  final String name;
  final String gender;
  final String description;
  final String? previewUrl;

  CatalogVoiceDto({
    required this.id,
    required this.name,
    required this.gender,
    required this.description,
    this.previewUrl,
  });

  factory CatalogVoiceDto.fromJson(Map<String, dynamic> json) =>
      _$CatalogVoiceDtoFromJson(json);
  Map<String, dynamic> toJson() => _$CatalogVoiceDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class UserSourceDto {
  final String id;
  final String sourceId;
  final String name;
  final String rssUrl;
  final bool isCustom;
  final bool enabled;

  UserSourceDto({
    required this.id,
    required this.sourceId,
    required this.name,
    required this.rssUrl,
    required this.isCustom,
    required this.enabled,
  });

  factory UserSourceDto.fromJson(Map<String, dynamic> json) =>
      _$UserSourceDtoFromJson(json);
  Map<String, dynamic> toJson() => _$UserSourceDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class PodcastProfileDto {
  final String title;
  final String formatPreset;
  final String hostPrimaryName;
  final String? hostSecondaryName;
  final List<String> guestNames;
  final int desiredDurationMinutes;
  final String? voiceId;
  final String? secondaryVoiceId;
  final String? tone;
  final int? keyFindingsCount;
  final String? humorStyle;
  final bool? personalizedGreeting;
  final bool? includeTopTakeaways;
  final bool? includeWeather;
  final String? weatherLocation;
  // Coordinates of the picked city (from the Open-Meteo geocoder) so the backend
  // forecasts the exact place instead of re-geocoding the ambiguous string;
  // weatherCountryCode drives °F/°C. All null for free-typed/legacy values.
  final double? weatherLat;
  final double? weatherLon;
  final String? weatherCountryCode;
  final String? customGuidance;
  final String? customGuidancePresetId;

  PodcastProfileDto({
    required this.title,
    required this.formatPreset,
    required this.hostPrimaryName,
    this.hostSecondaryName,
    required this.guestNames,
    required this.desiredDurationMinutes,
    this.voiceId,
    this.secondaryVoiceId,
    this.tone,
    this.keyFindingsCount,
    this.humorStyle,
    this.personalizedGreeting,
    this.includeTopTakeaways,
    this.includeWeather,
    this.weatherLocation,
    this.weatherLat,
    this.weatherLon,
    this.weatherCountryCode,
    this.customGuidance,
    this.customGuidancePresetId,
  });

  factory PodcastProfileDto.fromJson(Map<String, dynamic> json) =>
      _$PodcastProfileDtoFromJson(json);
  Map<String, dynamic> toJson() => _$PodcastProfileDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class DeliveryScheduleDto {
  final String timezone;
  final List<String> weekdays;
  final String localTime;
  final String cutoffTime;

  DeliveryScheduleDto({
    required this.timezone,
    required this.weekdays,
    required this.localTime,
    required this.cutoffTime,
  });

  factory DeliveryScheduleDto.fromJson(Map<String, dynamic> json) =>
      _$DeliveryScheduleDtoFromJson(json);
  Map<String, dynamic> toJson() => _$DeliveryScheduleDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class UserEpisodeDto {
  final String id;
  final String title;
  final String description;
  final DateTime publishedAt;
  final int? durationSeconds;
  final int processedItemCount;
  final int droppedItemCount;
  final bool capHit;
  final String? transcriptText;

  UserEpisodeDto({
    required this.id,
    required this.title,
    required this.description,
    required this.publishedAt,
    this.durationSeconds,
    required this.processedItemCount,
    required this.droppedItemCount,
    required this.capHit,
    this.transcriptText,
  });

  factory UserEpisodeDto.fromJson(Map<String, dynamic> json) =>
      _$UserEpisodeDtoFromJson(json);
  Map<String, dynamic> toJson() => _$UserEpisodeDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class UserRunDto {
  final String? id;
  final String status;
  final String message;
  final int candidateCount;
  final bool capHit;
  final String? publishedEpisodeId;

  UserRunDto({
    this.id,
    required this.status,
    required this.message,
    required this.candidateCount,
    required this.capHit,
    this.publishedEpisodeId,
  });

  factory UserRunDto.fromJson(Map<String, dynamic> json) =>
      _$UserRunDtoFromJson(json);
  Map<String, dynamic> toJson() => _$UserRunDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class RunStartEnvelope {
  final UserRunDto run;
  final bool started;

  RunStartEnvelope({required this.run, required this.started});

  factory RunStartEnvelope.fromJson(Map<String, dynamic> json) =>
      _$RunStartEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$RunStartEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class RunStatusEnvelope {
  final UserRunDto run;
  final UserEpisodeDto? episode;

  RunStatusEnvelope({required this.run, this.episode});

  factory RunStatusEnvelope.fromJson(Map<String, dynamic> json) =>
      _$RunStatusEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$RunStatusEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class InboundItemsEnvelope {
  final String? inboundAddress;
  final List<InboundItemDto> items;

  InboundItemsEnvelope({this.inboundAddress, required this.items});

  factory InboundItemsEnvelope.fromJson(Map<String, dynamic> json) =>
      _$InboundItemsEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$InboundItemsEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class InboundItemDto {
  final String id;
  final String fromEmail;
  final String? fromName;
  final String senderDomain;
  final String subject;
  final String? articleUrl;
  final DateTime receivedAt;

  InboundItemDto({
    required this.id,
    required this.fromEmail,
    this.fromName,
    required this.senderDomain,
    required this.subject,
    this.articleUrl,
    required this.receivedAt,
  });

  factory InboundItemDto.fromJson(Map<String, dynamic> json) =>
      _$InboundItemDtoFromJson(json);
  Map<String, dynamic> toJson() => _$InboundItemDtoToJson(this);

  String get displaySender {
    final name = fromName;
    if (name != null && name.isNotEmpty) return name;
    return senderDomain;
  }
}

// ---------------------------------------------------------------------------
// Substack
// ---------------------------------------------------------------------------

@JsonSerializable(fieldRename: FieldRename.snake)
class SubstackProbeDto {
  final String pubUrl;
  final String pubHost;
  final String? title;
  final String? author;
  final String? iconUrl;
  final bool hasPaidTier;
  final String feedUrl;

  SubstackProbeDto({
    required this.pubUrl,
    required this.pubHost,
    this.title,
    this.author,
    this.iconUrl,
    required this.hasPaidTier,
    required this.feedUrl,
  });

  factory SubstackProbeDto.fromJson(Map<String, dynamic> json) =>
      _$SubstackProbeDtoFromJson(json);
  Map<String, dynamic> toJson() => _$SubstackProbeDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SubstackCandidateDto {
  final String pubUrl;
  final String pubHost;
  final String? title;
  final String? author;
  final String? iconUrl;
  final bool hasPaidTier;
  final String feedUrl;
  final String? why;

  SubstackCandidateDto({
    required this.pubUrl,
    required this.pubHost,
    this.title,
    this.author,
    this.iconUrl,
    required this.hasPaidTier,
    required this.feedUrl,
    this.why,
  });

  factory SubstackCandidateDto.fromJson(Map<String, dynamic> json) =>
      _$SubstackCandidateDtoFromJson(json);
  Map<String, dynamic> toJson() => _$SubstackCandidateDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SubstackDiscoveryEnvelope {
  final List<SubstackCandidateDto> candidates;

  SubstackDiscoveryEnvelope({required this.candidates});

  factory SubstackDiscoveryEnvelope.fromJson(Map<String, dynamic> json) =>
      _$SubstackDiscoveryEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$SubstackDiscoveryEnvelopeToJson(this);
}

enum SubstackIntentStatus {
  @JsonValue('pending')
  pending,
  @JsonValue('auto_confirmed')
  autoConfirmed,
  @JsonValue('confirmed')
  confirmed,
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SubstackIntentDto {
  final String id;
  final String userId;
  final String pubUrl;
  final String pubHost;
  final String? pubTitle;
  final String? pubAuthor;
  final String? pubIconUrl;
  final bool hasPaidTier;
  final String aliasEmail;
  final DateTime createdAt;
  final DateTime? autoConfirmedAt;
  final DateTime? confirmedAt;
  final SubstackIntentStatus status;
  final String? pendingVerificationCode;
  final DateTime? pendingVerificationExpiresAt;

  SubstackIntentDto({
    required this.id,
    required this.userId,
    required this.pubUrl,
    required this.pubHost,
    this.pubTitle,
    this.pubAuthor,
    this.pubIconUrl,
    required this.hasPaidTier,
    required this.aliasEmail,
    required this.createdAt,
    this.autoConfirmedAt,
    this.confirmedAt,
    required this.status,
    this.pendingVerificationCode,
    this.pendingVerificationExpiresAt,
  });

  factory SubstackIntentDto.fromJson(Map<String, dynamic> json) =>
      _$SubstackIntentDtoFromJson(json);
  Map<String, dynamic> toJson() => _$SubstackIntentDtoToJson(this);

  /// True if a verification code is stamped and not yet expired.
  bool get hasLiveVerificationCode {
    final code = pendingVerificationCode;
    final expires = pendingVerificationExpiresAt;
    if (code == null || code.isEmpty || expires == null) return false;
    return expires.isAfter(DateTime.now());
  }

  String get displayTitle {
    final title = pubTitle;
    if (title != null && title.isNotEmpty) return title;
    return pubHost;
  }

  /// An intent stays `pending` until a real post arrives (status==confirmed);
  /// the intermediate `autoConfirmed` state is internal-only.
  SubstackIntentStatus get displayStatus =>
      status == SubstackIntentStatus.confirmed
          ? SubstackIntentStatus.confirmed
          : SubstackIntentStatus.pending;

  Uri? get subscribeUrl => Uri.tryParse('$pubUrl/subscribe');
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SubstackIntentsEnvelope {
  final String? inboundAddress;
  final List<SubstackIntentDto> intents;

  SubstackIntentsEnvelope({this.inboundAddress, required this.intents});

  factory SubstackIntentsEnvelope.fromJson(Map<String, dynamic> json) =>
      _$SubstackIntentsEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$SubstackIntentsEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SubstackIntentEnvelope {
  final SubstackIntentDto intent;

  SubstackIntentEnvelope({required this.intent});

  factory SubstackIntentEnvelope.fromJson(Map<String, dynamic> json) =>
      _$SubstackIntentEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$SubstackIntentEnvelopeToJson(this);
}

// ---------------------------------------------------------------------------
// Library / episodes
// ---------------------------------------------------------------------------

@JsonSerializable(fieldRename: FieldRename.snake)
class EpisodesEnvelope {
  final List<LibraryEpisodeDto> episodes;

  EpisodesEnvelope({required this.episodes});

  factory EpisodesEnvelope.fromJson(Map<String, dynamic> json) =>
      _$EpisodesEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$EpisodesEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SourceItemRefDto {
  final String sourceId;
  final String sourceName;
  final String title;
  final String link;
  final String? guid;

  SourceItemRefDto({
    required this.sourceId,
    required this.sourceName,
    required this.title,
    required this.link,
    this.guid,
  });

  factory SourceItemRefDto.fromJson(Map<String, dynamic> json) =>
      _$SourceItemRefDtoFromJson(json);
  Map<String, dynamic> toJson() => _$SourceItemRefDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class LibraryEpisodeDto {
  final String id;
  final String title;
  final String description;
  final DateTime publishedAt;
  final int? durationSeconds;
  final int processedItemCount;
  final int droppedItemCount;
  final bool capHit;
  final List<SourceItemRefDto> sourceItemRefs;
  final String? transcriptText;

  LibraryEpisodeDto({
    required this.id,
    required this.title,
    required this.description,
    required this.publishedAt,
    this.durationSeconds,
    required this.processedItemCount,
    required this.droppedItemCount,
    required this.capHit,
    required this.sourceItemRefs,
    this.transcriptText,
  });

  factory LibraryEpisodeDto.fromJson(Map<String, dynamic> json) =>
      _$LibraryEpisodeDtoFromJson(json);
  Map<String, dynamic> toJson() => _$LibraryEpisodeDtoToJson(this);
}

// ---------------------------------------------------------------------------
// Swipe deck + next-episode queue
// ---------------------------------------------------------------------------

@JsonSerializable(fieldRename: FieldRename.snake)
class SwipeDeckEnvelope {
  final List<SwipeDeckCardDto> items;

  SwipeDeckEnvelope({required this.items});

  factory SwipeDeckEnvelope.fromJson(Map<String, dynamic> json) =>
      _$SwipeDeckEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$SwipeDeckEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class NextEpisodeQueueEnvelope {
  @JsonKey(defaultValue: false)
  final bool enabled;
  @JsonKey(defaultValue: <NextEpisodeCandidateDto>[])
  final List<NextEpisodeCandidateDto> candidates;
  @JsonKey(defaultValue: 0)
  final int pinnedCount;
  @JsonKey(defaultValue: 0)
  final int maxPins;
  @JsonKey(defaultValue: 0)
  final int pinsRemaining;
  @JsonKey(defaultValue: false)
  final bool rankerUsed;

  NextEpisodeQueueEnvelope({
    this.enabled = false,
    this.candidates = const [],
    this.pinnedCount = 0,
    this.maxPins = 0,
    this.pinsRemaining = 0,
    this.rankerUsed = false,
  });

  factory NextEpisodeQueueEnvelope.fromJson(Map<String, dynamic> json) =>
      _$NextEpisodeQueueEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$NextEpisodeQueueEnvelopeToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class NextEpisodeCandidateDto {
  final String dedupeKey;
  final String sourceId;
  final String sourceName;
  final String title;
  final String summary;
  final String link;
  final DateTime publishedAt;
  final bool pinned;
  final bool likelyIncluded;

  /// True for items shared via the iOS Share extension / POST /v1/items/shared.
  /// Old builds default to false.
  @JsonKey(defaultValue: false)
  final bool shared;

  NextEpisodeCandidateDto({
    required this.dedupeKey,
    required this.sourceId,
    required this.sourceName,
    required this.title,
    required this.summary,
    required this.link,
    required this.publishedAt,
    required this.pinned,
    required this.likelyIncluded,
    this.shared = false,
  });

  factory NextEpisodeCandidateDto.fromJson(Map<String, dynamic> json) =>
      _$NextEpisodeCandidateDtoFromJson(json);
  Map<String, dynamic> toJson() => _$NextEpisodeCandidateDtoToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class SwipeDeckCardDto {
  final String sourceItemDedupeKey;
  final String title;
  final String summary;

  /// LLM-generated brief summary; preferred over the raw `summary` (often
  /// unstripped HTML / feed boilerplate).
  final String? cardSummary;
  final String sourceId;
  final String sourceName;
  final String link;
  final DateTime publishedAt;

  SwipeDeckCardDto({
    required this.sourceItemDedupeKey,
    required this.title,
    required this.summary,
    this.cardSummary,
    required this.sourceId,
    required this.sourceName,
    required this.link,
    required this.publishedAt,
  });

  factory SwipeDeckCardDto.fromJson(Map<String, dynamic> json) =>
      _$SwipeDeckCardDtoFromJson(json);
  Map<String, dynamic> toJson() => _$SwipeDeckCardDtoToJson(this);

  /// Best-available human-readable summary. Prefers `cardSummary`; falls back
  /// to a tag-stripped, whitespace-collapsed, 280-char-capped `summary`.
  String get displaySummary {
    final card = cardSummary;
    if (card != null && card.isNotEmpty) return card;
    return _cleanFallback(summary);
  }

  static String _cleanFallback(String raw) {
    final withoutTags = raw.replaceAll(RegExp(r'<[^>]+>'), ' ');
    final collapsed =
        withoutTags.replaceAll(RegExp(r'\s+'), ' ').trim();
    if (collapsed.length <= 280) return collapsed;
    return '${collapsed.substring(0, 280).trim()}…';
  }
}
