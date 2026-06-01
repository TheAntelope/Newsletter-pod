// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'responses.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

CorpusRefreshAck _$CorpusRefreshAckFromJson(Map<String, dynamic> json) =>
    CorpusRefreshAck(
      sourcesProcessed: (json['sources_processed'] as num).toInt(),
      itemsIngested: (json['items_ingested'] as num).toInt(),
    );

Map<String, dynamic> _$CorpusRefreshAckToJson(CorpusRefreshAck instance) =>
    <String, dynamic>{
      'sources_processed': instance.sourcesProcessed,
      'items_ingested': instance.itemsIngested,
    };

DeviceTokenAck _$DeviceTokenAckFromJson(Map<String, dynamic> json) =>
    DeviceTokenAck(
      tokenId: json['token_id'] as String,
      status: json['status'] as String,
    );

Map<String, dynamic> _$DeviceTokenAckToJson(DeviceTokenAck instance) =>
    <String, dynamic>{'token_id': instance.tokenId, 'status': instance.status};

VoiceIntakeAck _$VoiceIntakeAckFromJson(Map<String, dynamic> json) =>
    VoiceIntakeAck(
      seededCount: (json['seeded_count'] as num).toInt(),
      topics: (json['topics'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      namedEntities: (json['named_entities'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      anchorPhrases: (json['anchor_phrases'] as List<dynamic>)
          .map((e) => e as String)
          .toList(),
      vibeNotes: json['vibe_notes'] as String?,
    );

Map<String, dynamic> _$VoiceIntakeAckToJson(VoiceIntakeAck instance) =>
    <String, dynamic>{
      'seeded_count': instance.seededCount,
      'topics': instance.topics,
      'named_entities': instance.namedEntities,
      'anchor_phrases': instance.anchorPhrases,
      'vibe_notes': instance.vibeNotes,
    };

AccountDeletionAck _$AccountDeletionAckFromJson(Map<String, dynamic> json) =>
    AccountDeletionAck(
      userId: json['user_id'] as String,
      alreadyDeleted: json['already_deleted'] as bool,
      audioObjectsDeleted: (json['audio_objects_deleted'] as num).toInt(),
    );

Map<String, dynamic> _$AccountDeletionAckToJson(AccountDeletionAck instance) =>
    <String, dynamic>{
      'user_id': instance.userId,
      'already_deleted': instance.alreadyDeleted,
      'audio_objects_deleted': instance.audioObjectsDeleted,
    };

AccountResetAck _$AccountResetAckFromJson(Map<String, dynamic> json) =>
    AccountResetAck(userId: json['user_id'] as String);

Map<String, dynamic> _$AccountResetAckToJson(AccountResetAck instance) =>
    <String, dynamic>{'user_id': instance.userId};

VerifySubscriptionPayload _$VerifySubscriptionPayloadFromJson(
  Map<String, dynamic> json,
) => VerifySubscriptionPayload(
  tier: json['tier'] as String,
  status: json['status'] as String?,
  productId: json['product_id'] as String?,
  expiresAt: json['expires_at'] as String?,
);

Map<String, dynamic> _$VerifySubscriptionPayloadToJson(
  VerifySubscriptionPayload instance,
) => <String, dynamic>{
  'tier': instance.tier,
  'status': instance.status,
  'product_id': instance.productId,
  'expires_at': instance.expiresAt,
};

VerifySubscriptionEnvelope _$VerifySubscriptionEnvelopeFromJson(
  Map<String, dynamic> json,
) => VerifySubscriptionEnvelope(
  accepted: json['accepted'] as bool,
  eventId: json['event_id'] as String?,
  subscription: json['subscription'] == null
      ? null
      : VerifySubscriptionPayload.fromJson(
          json['subscription'] as Map<String, dynamic>,
        ),
);

Map<String, dynamic> _$VerifySubscriptionEnvelopeToJson(
  VerifySubscriptionEnvelope instance,
) => <String, dynamic>{
  'accepted': instance.accepted,
  'event_id': instance.eventId,
  'subscription': instance.subscription,
};
