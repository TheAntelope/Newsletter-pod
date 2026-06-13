// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'models.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

SessionEnvelope _$SessionEnvelopeFromJson(Map<String, dynamic> json) =>
    SessionEnvelope(
      sessionToken: json['session_token'] as String,
      isNewUser: json['is_new_user'] as bool,
      user: UserDto.fromJson(json['user'] as Map<String, dynamic>),
      subscription: SubscriptionDto.fromJson(
        json['subscription'] as Map<String, dynamic>,
      ),
    );

Map<String, dynamic> _$SessionEnvelopeToJson(SessionEnvelope instance) =>
    <String, dynamic>{
      'session_token': instance.sessionToken,
      'is_new_user': instance.isNewUser,
      'user': instance.user,
      'subscription': instance.subscription,
    };

MeEnvelope _$MeEnvelopeFromJson(Map<String, dynamic> json) => MeEnvelope(
  user: UserDto.fromJson(json['user'] as Map<String, dynamic>),
  profile: PodcastProfileDto.fromJson(json['profile'] as Map<String, dynamic>),
  schedule: DeliveryScheduleDto.fromJson(
    json['schedule'] as Map<String, dynamic>,
  ),
  subscription: SubscriptionDto.fromJson(
    json['subscription'] as Map<String, dynamic>,
  ),
  entitlements: EntitlementsDto.fromJson(
    json['entitlements'] as Map<String, dynamic>,
  ),
);

Map<String, dynamic> _$MeEnvelopeToJson(MeEnvelope instance) =>
    <String, dynamic>{
      'user': instance.user,
      'profile': instance.profile,
      'schedule': instance.schedule,
      'subscription': instance.subscription,
      'entitlements': instance.entitlements,
    };

SourcesEnvelope _$SourcesEnvelopeFromJson(Map<String, dynamic> json) =>
    SourcesEnvelope(
      sources: (json['sources'] as List<dynamic>)
          .map((e) => UserSourceDto.fromJson(e as Map<String, dynamic>))
          .toList(),
      entitlements: EntitlementsDto.fromJson(
        json['entitlements'] as Map<String, dynamic>,
      ),
    );

Map<String, dynamic> _$SourcesEnvelopeToJson(SourcesEnvelope instance) =>
    <String, dynamic>{
      'sources': instance.sources,
      'entitlements': instance.entitlements,
    };

CatalogEnvelope _$CatalogEnvelopeFromJson(Map<String, dynamic> json) =>
    CatalogEnvelope(
      sources: (json['sources'] as List<dynamic>)
          .map((e) => CatalogSourceDto.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$CatalogEnvelopeToJson(CatalogEnvelope instance) =>
    <String, dynamic>{'sources': instance.sources};

VoiceCatalogEnvelope _$VoiceCatalogEnvelopeFromJson(
  Map<String, dynamic> json,
) => VoiceCatalogEnvelope(
  voices: (json['voices'] as List<dynamic>)
      .map((e) => CatalogVoiceDto.fromJson(e as Map<String, dynamic>))
      .toList(),
);

Map<String, dynamic> _$VoiceCatalogEnvelopeToJson(
  VoiceCatalogEnvelope instance,
) => <String, dynamic>{'voices': instance.voices};

PodcastConfigEnvelope _$PodcastConfigEnvelopeFromJson(
  Map<String, dynamic> json,
) => PodcastConfigEnvelope(
  profile: PodcastProfileDto.fromJson(json['profile'] as Map<String, dynamic>),
  entitlements: EntitlementsDto.fromJson(
    json['entitlements'] as Map<String, dynamic>,
  ),
);

Map<String, dynamic> _$PodcastConfigEnvelopeToJson(
  PodcastConfigEnvelope instance,
) => <String, dynamic>{
  'profile': instance.profile,
  'entitlements': instance.entitlements,
};

ScheduleEnvelope _$ScheduleEnvelopeFromJson(Map<String, dynamic> json) =>
    ScheduleEnvelope(
      schedule: DeliveryScheduleDto.fromJson(
        json['schedule'] as Map<String, dynamic>,
      ),
      entitlements: EntitlementsDto.fromJson(
        json['entitlements'] as Map<String, dynamic>,
      ),
    );

Map<String, dynamic> _$ScheduleEnvelopeToJson(ScheduleEnvelope instance) =>
    <String, dynamic>{
      'schedule': instance.schedule,
      'entitlements': instance.entitlements,
    };

FeedEnvelope _$FeedEnvelopeFromJson(Map<String, dynamic> json) => FeedEnvelope(
  feedUrl: json['feed_url'] as String,
  token: json['token'] as String,
  latestEpisode: json['latest_episode'] == null
      ? null
      : UserEpisodeDto.fromJson(json['latest_episode'] as Map<String, dynamic>),
  latestRun: json['latest_run'] == null
      ? null
      : UserRunDto.fromJson(json['latest_run'] as Map<String, dynamic>),
  subscription: SubscriptionDto.fromJson(
    json['subscription'] as Map<String, dynamic>,
  ),
  entitlements: EntitlementsDto.fromJson(
    json['entitlements'] as Map<String, dynamic>,
  ),
);

Map<String, dynamic> _$FeedEnvelopeToJson(FeedEnvelope instance) =>
    <String, dynamic>{
      'feed_url': instance.feedUrl,
      'token': instance.token,
      'latest_episode': instance.latestEpisode,
      'latest_run': instance.latestRun,
      'subscription': instance.subscription,
      'entitlements': instance.entitlements,
    };

UserDto _$UserDtoFromJson(Map<String, dynamic> json) => UserDto(
  id: json['id'] as String,
  email: json['email'] as String?,
  displayName: json['display_name'] as String,
  timezone: json['timezone'] as String,
  inboundAddress: json['inbound_address'] as String?,
);

Map<String, dynamic> _$UserDtoToJson(UserDto instance) => <String, dynamic>{
  'id': instance.id,
  'email': instance.email,
  'display_name': instance.displayName,
  'timezone': instance.timezone,
  'inbound_address': instance.inboundAddress,
};

SubscriptionDto _$SubscriptionDtoFromJson(Map<String, dynamic> json) =>
    SubscriptionDto(
      userId: json['user_id'] as String,
      tier: json['tier'] as String,
      status: json['status'] as String,
      productId: json['product_id'] as String?,
    );

Map<String, dynamic> _$SubscriptionDtoToJson(SubscriptionDto instance) =>
    <String, dynamic>{
      'user_id': instance.userId,
      'tier': instance.tier,
      'status': instance.status,
      'product_id': instance.productId,
    };

EntitlementsDto _$EntitlementsDtoFromJson(Map<String, dynamic> json) =>
    EntitlementsDto(
      tier: json['tier'] as String,
      maxDeliveryDays: (json['max_delivery_days'] as num).toInt(),
      minDurationMinutes: (json['min_duration_minutes'] as num).toInt(),
      maxDurationMinutes: (json['max_duration_minutes'] as num).toInt(),
      maxItemsPerEpisode: (json['max_items_per_episode'] as num).toInt(),
      premiumPodsPerWeek: (json['premium_pods_per_week'] as num?)?.toInt() ?? 0,
      defaultPodsPerWeek: (json['default_pods_per_week'] as num?)?.toInt() ?? 0,
      premiumPodsRemainingThisWeek:
          (json['premium_pods_remaining_this_week'] as num?)?.toInt() ?? 0,
      defaultPodsRemainingThisWeek:
          (json['default_pods_remaining_this_week'] as num?)?.toInt() ?? 0,
      isInTrial: json['is_in_trial'] as bool? ?? false,
      trialPremiumPodsRemaining:
          (json['trial_premium_pods_remaining'] as num?)?.toInt() ?? 0,
      isInFirstMonth: json['is_in_first_month'] as bool? ?? false,
      firstMonthEndsAt: json['first_month_ends_at'] == null
          ? null
          : DateTime.parse(json['first_month_ends_at'] as String),
      trialEndsAt: json['trial_ends_at'] == null
          ? null
          : DateTime.parse(json['trial_ends_at'] as String),
    );

Map<String, dynamic> _$EntitlementsDtoToJson(EntitlementsDto instance) =>
    <String, dynamic>{
      'tier': instance.tier,
      'max_delivery_days': instance.maxDeliveryDays,
      'min_duration_minutes': instance.minDurationMinutes,
      'max_duration_minutes': instance.maxDurationMinutes,
      'max_items_per_episode': instance.maxItemsPerEpisode,
      'premium_pods_per_week': instance.premiumPodsPerWeek,
      'default_pods_per_week': instance.defaultPodsPerWeek,
      'premium_pods_remaining_this_week': instance.premiumPodsRemainingThisWeek,
      'default_pods_remaining_this_week': instance.defaultPodsRemainingThisWeek,
      'is_in_trial': instance.isInTrial,
      'trial_premium_pods_remaining': instance.trialPremiumPodsRemaining,
      'is_in_first_month': instance.isInFirstMonth,
      'first_month_ends_at': instance.firstMonthEndsAt?.toIso8601String(),
      'trial_ends_at': instance.trialEndsAt?.toIso8601String(),
    };

CatalogSourceDto _$CatalogSourceDtoFromJson(Map<String, dynamic> json) =>
    CatalogSourceDto(
      sourceId: json['source_id'] as String,
      name: json['name'] as String,
      rssUrl: json['rss_url'] as String,
      enabled: json['enabled'] as bool,
      topic: json['topic'] as String?,
    );

Map<String, dynamic> _$CatalogSourceDtoToJson(CatalogSourceDto instance) =>
    <String, dynamic>{
      'source_id': instance.sourceId,
      'name': instance.name,
      'rss_url': instance.rssUrl,
      'enabled': instance.enabled,
      'topic': instance.topic,
    };

CatalogVoiceDto _$CatalogVoiceDtoFromJson(Map<String, dynamic> json) =>
    CatalogVoiceDto(
      id: json['id'] as String,
      name: json['name'] as String,
      gender: json['gender'] as String,
      description: json['description'] as String,
      previewUrl: json['preview_url'] as String?,
    );

Map<String, dynamic> _$CatalogVoiceDtoToJson(CatalogVoiceDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'name': instance.name,
      'gender': instance.gender,
      'description': instance.description,
      'preview_url': instance.previewUrl,
    };

UserSourceDto _$UserSourceDtoFromJson(Map<String, dynamic> json) =>
    UserSourceDto(
      id: json['id'] as String,
      sourceId: json['source_id'] as String,
      name: json['name'] as String,
      rssUrl: json['rss_url'] as String,
      isCustom: json['is_custom'] as bool,
      enabled: json['enabled'] as bool,
    );

Map<String, dynamic> _$UserSourceDtoToJson(UserSourceDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'source_id': instance.sourceId,
      'name': instance.name,
      'rss_url': instance.rssUrl,
      'is_custom': instance.isCustom,
      'enabled': instance.enabled,
    };

PodcastProfileDto _$PodcastProfileDtoFromJson(Map<String, dynamic> json) =>
    PodcastProfileDto(
      title: json['title'] as String,
      formatPreset: json['format_preset'] as String,
      hostPrimaryName: json['host_primary_name'] as String,
      hostSecondaryName: json['host_secondary_name'] as String?,
      guestNames: (json['guest_names'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      desiredDurationMinutes: (json['desired_duration_minutes'] as num).toInt(),
      voiceId: json['voice_id'] as String?,
      secondaryVoiceId: json['secondary_voice_id'] as String?,
      tone: json['tone'] as String?,
      keyFindingsCount: (json['key_findings_count'] as num?)?.toInt(),
      humorStyle: json['humor_style'] as String?,
      personalizedGreeting: json['personalized_greeting'] as bool?,
      includeTopTakeaways: json['include_top_takeaways'] as bool?,
      includeWeather: json['include_weather'] as bool?,
      weatherLocation: json['weather_location'] as String?,
      weatherLat: (json['weather_lat'] as num?)?.toDouble(),
      weatherLon: (json['weather_lon'] as num?)?.toDouble(),
      weatherCountryCode: json['weather_country_code'] as String?,
      customGuidance: json['custom_guidance'] as String?,
      customGuidancePresetId: json['custom_guidance_preset_id'] as String?,
    );

Map<String, dynamic> _$PodcastProfileDtoToJson(PodcastProfileDto instance) =>
    <String, dynamic>{
      'title': instance.title,
      'format_preset': instance.formatPreset,
      'host_primary_name': instance.hostPrimaryName,
      'host_secondary_name': instance.hostSecondaryName,
      'guest_names': instance.guestNames,
      'desired_duration_minutes': instance.desiredDurationMinutes,
      'voice_id': instance.voiceId,
      'secondary_voice_id': instance.secondaryVoiceId,
      'tone': instance.tone,
      'key_findings_count': instance.keyFindingsCount,
      'humor_style': instance.humorStyle,
      'personalized_greeting': instance.personalizedGreeting,
      'include_top_takeaways': instance.includeTopTakeaways,
      'include_weather': instance.includeWeather,
      'weather_location': instance.weatherLocation,
      'weather_lat': instance.weatherLat,
      'weather_lon': instance.weatherLon,
      'weather_country_code': instance.weatherCountryCode,
      'custom_guidance': instance.customGuidance,
      'custom_guidance_preset_id': instance.customGuidancePresetId,
    };

DeliveryScheduleDto _$DeliveryScheduleDtoFromJson(Map<String, dynamic> json) =>
    DeliveryScheduleDto(
      timezone: json['timezone'] as String,
      weekdays: (json['weekdays'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      localTime: json['local_time'] as String,
      cutoffTime: json['cutoff_time'] as String,
    );

Map<String, dynamic> _$DeliveryScheduleDtoToJson(
  DeliveryScheduleDto instance,
) => <String, dynamic>{
  'timezone': instance.timezone,
  'weekdays': instance.weekdays,
  'local_time': instance.localTime,
  'cutoff_time': instance.cutoffTime,
};

UserEpisodeDto _$UserEpisodeDtoFromJson(Map<String, dynamic> json) =>
    UserEpisodeDto(
      id: json['id'] as String,
      title: json['title'] as String,
      description: json['description'] as String,
      publishedAt: DateTime.parse(json['published_at'] as String),
      durationSeconds: (json['duration_seconds'] as num?)?.toInt(),
      processedItemCount: (json['processed_item_count'] as num).toInt(),
      droppedItemCount: (json['dropped_item_count'] as num).toInt(),
      capHit: json['cap_hit'] as bool,
      transcriptText: json['transcript_text'] as String?,
    );

Map<String, dynamic> _$UserEpisodeDtoToJson(UserEpisodeDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'title': instance.title,
      'description': instance.description,
      'published_at': instance.publishedAt.toIso8601String(),
      'duration_seconds': instance.durationSeconds,
      'processed_item_count': instance.processedItemCount,
      'dropped_item_count': instance.droppedItemCount,
      'cap_hit': instance.capHit,
      'transcript_text': instance.transcriptText,
    };

UserRunDto _$UserRunDtoFromJson(Map<String, dynamic> json) => UserRunDto(
  id: json['id'] as String?,
  status: json['status'] as String,
  message: json['message'] as String,
  candidateCount: (json['candidate_count'] as num).toInt(),
  capHit: json['cap_hit'] as bool,
  publishedEpisodeId: json['published_episode_id'] as String?,
);

Map<String, dynamic> _$UserRunDtoToJson(UserRunDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'status': instance.status,
      'message': instance.message,
      'candidate_count': instance.candidateCount,
      'cap_hit': instance.capHit,
      'published_episode_id': instance.publishedEpisodeId,
    };

RunStartEnvelope _$RunStartEnvelopeFromJson(Map<String, dynamic> json) =>
    RunStartEnvelope(
      run: UserRunDto.fromJson(json['run'] as Map<String, dynamic>),
      started: json['started'] as bool,
    );

Map<String, dynamic> _$RunStartEnvelopeToJson(RunStartEnvelope instance) =>
    <String, dynamic>{'run': instance.run, 'started': instance.started};

RunStatusEnvelope _$RunStatusEnvelopeFromJson(Map<String, dynamic> json) =>
    RunStatusEnvelope(
      run: UserRunDto.fromJson(json['run'] as Map<String, dynamic>),
      episode: json['episode'] == null
          ? null
          : UserEpisodeDto.fromJson(json['episode'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$RunStatusEnvelopeToJson(RunStatusEnvelope instance) =>
    <String, dynamic>{'run': instance.run, 'episode': instance.episode};

InboundItemsEnvelope _$InboundItemsEnvelopeFromJson(
  Map<String, dynamic> json,
) => InboundItemsEnvelope(
  inboundAddress: json['inbound_address'] as String?,
  items: (json['items'] as List<dynamic>)
      .map((e) => InboundItemDto.fromJson(e as Map<String, dynamic>))
      .toList(),
);

Map<String, dynamic> _$InboundItemsEnvelopeToJson(
  InboundItemsEnvelope instance,
) => <String, dynamic>{
  'inbound_address': instance.inboundAddress,
  'items': instance.items,
};

InboundItemDto _$InboundItemDtoFromJson(Map<String, dynamic> json) =>
    InboundItemDto(
      id: json['id'] as String,
      fromEmail: json['from_email'] as String,
      fromName: json['from_name'] as String?,
      senderDomain: json['sender_domain'] as String,
      subject: json['subject'] as String,
      articleUrl: json['article_url'] as String?,
      receivedAt: DateTime.parse(json['received_at'] as String),
    );

Map<String, dynamic> _$InboundItemDtoToJson(InboundItemDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'from_email': instance.fromEmail,
      'from_name': instance.fromName,
      'sender_domain': instance.senderDomain,
      'subject': instance.subject,
      'article_url': instance.articleUrl,
      'received_at': instance.receivedAt.toIso8601String(),
    };

SubstackProbeDto _$SubstackProbeDtoFromJson(Map<String, dynamic> json) =>
    SubstackProbeDto(
      pubUrl: json['pub_url'] as String,
      pubHost: json['pub_host'] as String,
      title: json['title'] as String?,
      author: json['author'] as String?,
      iconUrl: json['icon_url'] as String?,
      hasPaidTier: json['has_paid_tier'] as bool,
      feedUrl: json['feed_url'] as String,
    );

Map<String, dynamic> _$SubstackProbeDtoToJson(SubstackProbeDto instance) =>
    <String, dynamic>{
      'pub_url': instance.pubUrl,
      'pub_host': instance.pubHost,
      'title': instance.title,
      'author': instance.author,
      'icon_url': instance.iconUrl,
      'has_paid_tier': instance.hasPaidTier,
      'feed_url': instance.feedUrl,
    };

SubstackCandidateDto _$SubstackCandidateDtoFromJson(
  Map<String, dynamic> json,
) => SubstackCandidateDto(
  pubUrl: json['pub_url'] as String,
  pubHost: json['pub_host'] as String,
  title: json['title'] as String?,
  author: json['author'] as String?,
  iconUrl: json['icon_url'] as String?,
  hasPaidTier: json['has_paid_tier'] as bool,
  feedUrl: json['feed_url'] as String,
  why: json['why'] as String?,
);

Map<String, dynamic> _$SubstackCandidateDtoToJson(
  SubstackCandidateDto instance,
) => <String, dynamic>{
  'pub_url': instance.pubUrl,
  'pub_host': instance.pubHost,
  'title': instance.title,
  'author': instance.author,
  'icon_url': instance.iconUrl,
  'has_paid_tier': instance.hasPaidTier,
  'feed_url': instance.feedUrl,
  'why': instance.why,
};

SubstackDiscoveryEnvelope _$SubstackDiscoveryEnvelopeFromJson(
  Map<String, dynamic> json,
) => SubstackDiscoveryEnvelope(
  candidates: (json['candidates'] as List<dynamic>)
      .map((e) => SubstackCandidateDto.fromJson(e as Map<String, dynamic>))
      .toList(),
);

Map<String, dynamic> _$SubstackDiscoveryEnvelopeToJson(
  SubstackDiscoveryEnvelope instance,
) => <String, dynamic>{'candidates': instance.candidates};

SubstackIntentDto _$SubstackIntentDtoFromJson(Map<String, dynamic> json) =>
    SubstackIntentDto(
      id: json['id'] as String,
      userId: json['user_id'] as String,
      pubUrl: json['pub_url'] as String,
      pubHost: json['pub_host'] as String,
      pubTitle: json['pub_title'] as String?,
      pubAuthor: json['pub_author'] as String?,
      pubIconUrl: json['pub_icon_url'] as String?,
      hasPaidTier: json['has_paid_tier'] as bool,
      aliasEmail: json['alias_email'] as String,
      createdAt: DateTime.parse(json['created_at'] as String),
      autoConfirmedAt: json['auto_confirmed_at'] == null
          ? null
          : DateTime.parse(json['auto_confirmed_at'] as String),
      confirmedAt: json['confirmed_at'] == null
          ? null
          : DateTime.parse(json['confirmed_at'] as String),
      status: $enumDecode(_$SubstackIntentStatusEnumMap, json['status']),
      pendingVerificationCode: json['pending_verification_code'] as String?,
      pendingVerificationExpiresAt:
          json['pending_verification_expires_at'] == null
          ? null
          : DateTime.parse(json['pending_verification_expires_at'] as String),
    );

Map<String, dynamic> _$SubstackIntentDtoToJson(SubstackIntentDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'user_id': instance.userId,
      'pub_url': instance.pubUrl,
      'pub_host': instance.pubHost,
      'pub_title': instance.pubTitle,
      'pub_author': instance.pubAuthor,
      'pub_icon_url': instance.pubIconUrl,
      'has_paid_tier': instance.hasPaidTier,
      'alias_email': instance.aliasEmail,
      'created_at': instance.createdAt.toIso8601String(),
      'auto_confirmed_at': instance.autoConfirmedAt?.toIso8601String(),
      'confirmed_at': instance.confirmedAt?.toIso8601String(),
      'status': _$SubstackIntentStatusEnumMap[instance.status]!,
      'pending_verification_code': instance.pendingVerificationCode,
      'pending_verification_expires_at': instance.pendingVerificationExpiresAt
          ?.toIso8601String(),
    };

const _$SubstackIntentStatusEnumMap = {
  SubstackIntentStatus.pending: 'pending',
  SubstackIntentStatus.autoConfirmed: 'auto_confirmed',
  SubstackIntentStatus.confirmed: 'confirmed',
};

SubstackIntentsEnvelope _$SubstackIntentsEnvelopeFromJson(
  Map<String, dynamic> json,
) => SubstackIntentsEnvelope(
  inboundAddress: json['inbound_address'] as String?,
  intents: (json['intents'] as List<dynamic>)
      .map((e) => SubstackIntentDto.fromJson(e as Map<String, dynamic>))
      .toList(),
);

Map<String, dynamic> _$SubstackIntentsEnvelopeToJson(
  SubstackIntentsEnvelope instance,
) => <String, dynamic>{
  'inbound_address': instance.inboundAddress,
  'intents': instance.intents,
};

SubstackIntentEnvelope _$SubstackIntentEnvelopeFromJson(
  Map<String, dynamic> json,
) => SubstackIntentEnvelope(
  intent: SubstackIntentDto.fromJson(json['intent'] as Map<String, dynamic>),
);

Map<String, dynamic> _$SubstackIntentEnvelopeToJson(
  SubstackIntentEnvelope instance,
) => <String, dynamic>{'intent': instance.intent};

EpisodesEnvelope _$EpisodesEnvelopeFromJson(Map<String, dynamic> json) =>
    EpisodesEnvelope(
      episodes: (json['episodes'] as List<dynamic>)
          .map((e) => LibraryEpisodeDto.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$EpisodesEnvelopeToJson(EpisodesEnvelope instance) =>
    <String, dynamic>{'episodes': instance.episodes};

SourceItemRefDto _$SourceItemRefDtoFromJson(Map<String, dynamic> json) =>
    SourceItemRefDto(
      sourceId: json['source_id'] as String,
      sourceName: json['source_name'] as String,
      title: json['title'] as String,
      link: json['link'] as String,
      guid: json['guid'] as String?,
    );

Map<String, dynamic> _$SourceItemRefDtoToJson(SourceItemRefDto instance) =>
    <String, dynamic>{
      'source_id': instance.sourceId,
      'source_name': instance.sourceName,
      'title': instance.title,
      'link': instance.link,
      'guid': instance.guid,
    };

LibraryEpisodeDto _$LibraryEpisodeDtoFromJson(Map<String, dynamic> json) =>
    LibraryEpisodeDto(
      id: json['id'] as String,
      title: json['title'] as String,
      description: json['description'] as String,
      publishedAt: DateTime.parse(json['published_at'] as String),
      durationSeconds: (json['duration_seconds'] as num?)?.toInt(),
      processedItemCount: (json['processed_item_count'] as num).toInt(),
      droppedItemCount: (json['dropped_item_count'] as num).toInt(),
      capHit: json['cap_hit'] as bool,
      sourceItemRefs: (json['source_item_refs'] as List<dynamic>)
          .map((e) => SourceItemRefDto.fromJson(e as Map<String, dynamic>))
          .toList(),
      transcriptText: json['transcript_text'] as String?,
    );

Map<String, dynamic> _$LibraryEpisodeDtoToJson(LibraryEpisodeDto instance) =>
    <String, dynamic>{
      'id': instance.id,
      'title': instance.title,
      'description': instance.description,
      'published_at': instance.publishedAt.toIso8601String(),
      'duration_seconds': instance.durationSeconds,
      'processed_item_count': instance.processedItemCount,
      'dropped_item_count': instance.droppedItemCount,
      'cap_hit': instance.capHit,
      'source_item_refs': instance.sourceItemRefs,
      'transcript_text': instance.transcriptText,
    };

SwipeDeckEnvelope _$SwipeDeckEnvelopeFromJson(Map<String, dynamic> json) =>
    SwipeDeckEnvelope(
      items: (json['items'] as List<dynamic>)
          .map((e) => SwipeDeckCardDto.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$SwipeDeckEnvelopeToJson(SwipeDeckEnvelope instance) =>
    <String, dynamic>{'items': instance.items};

NextEpisodeQueueEnvelope _$NextEpisodeQueueEnvelopeFromJson(
  Map<String, dynamic> json,
) => NextEpisodeQueueEnvelope(
  enabled: json['enabled'] as bool? ?? false,
  candidates:
      (json['candidates'] as List<dynamic>?)
          ?.map(
            (e) => NextEpisodeCandidateDto.fromJson(e as Map<String, dynamic>),
          )
          .toList() ??
      [],
  pinnedCount: (json['pinned_count'] as num?)?.toInt() ?? 0,
  maxPins: (json['max_pins'] as num?)?.toInt() ?? 0,
  pinsRemaining: (json['pins_remaining'] as num?)?.toInt() ?? 0,
  rankerUsed: json['ranker_used'] as bool? ?? false,
);

Map<String, dynamic> _$NextEpisodeQueueEnvelopeToJson(
  NextEpisodeQueueEnvelope instance,
) => <String, dynamic>{
  'enabled': instance.enabled,
  'candidates': instance.candidates,
  'pinned_count': instance.pinnedCount,
  'max_pins': instance.maxPins,
  'pins_remaining': instance.pinsRemaining,
  'ranker_used': instance.rankerUsed,
};

NextEpisodeCandidateDto _$NextEpisodeCandidateDtoFromJson(
  Map<String, dynamic> json,
) => NextEpisodeCandidateDto(
  dedupeKey: json['dedupe_key'] as String,
  sourceId: json['source_id'] as String,
  sourceName: json['source_name'] as String,
  title: json['title'] as String,
  summary: json['summary'] as String,
  link: json['link'] as String,
  publishedAt: DateTime.parse(json['published_at'] as String),
  pinned: json['pinned'] as bool,
  likelyIncluded: json['likely_included'] as bool,
  shared: json['shared'] as bool? ?? false,
);

Map<String, dynamic> _$NextEpisodeCandidateDtoToJson(
  NextEpisodeCandidateDto instance,
) => <String, dynamic>{
  'dedupe_key': instance.dedupeKey,
  'source_id': instance.sourceId,
  'source_name': instance.sourceName,
  'title': instance.title,
  'summary': instance.summary,
  'link': instance.link,
  'published_at': instance.publishedAt.toIso8601String(),
  'pinned': instance.pinned,
  'likely_included': instance.likelyIncluded,
  'shared': instance.shared,
};

SwipeDeckCardDto _$SwipeDeckCardDtoFromJson(Map<String, dynamic> json) =>
    SwipeDeckCardDto(
      sourceItemDedupeKey: json['source_item_dedupe_key'] as String,
      title: json['title'] as String,
      summary: json['summary'] as String,
      cardSummary: json['card_summary'] as String?,
      sourceId: json['source_id'] as String,
      sourceName: json['source_name'] as String,
      link: json['link'] as String,
      publishedAt: DateTime.parse(json['published_at'] as String),
    );

Map<String, dynamic> _$SwipeDeckCardDtoToJson(SwipeDeckCardDto instance) =>
    <String, dynamic>{
      'source_item_dedupe_key': instance.sourceItemDedupeKey,
      'title': instance.title,
      'summary': instance.summary,
      'card_summary': instance.cardSummary,
      'source_id': instance.sourceId,
      'source_name': instance.sourceName,
      'link': instance.link,
      'published_at': instance.publishedAt.toIso8601String(),
    };
