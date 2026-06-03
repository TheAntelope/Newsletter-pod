// Dart port of the response/ack types defined in ios/.../APIClient.swift
// (the ones not in APIModels.swift). FieldRename.snake maps the snake_case keys.
import 'package:json_annotation/json_annotation.dart';

part 'responses.g.dart';

@JsonSerializable(fieldRename: FieldRename.snake)
class CorpusRefreshAck {
  final int sourcesProcessed;
  final int itemsIngested;

  CorpusRefreshAck({required this.sourcesProcessed, required this.itemsIngested});

  factory CorpusRefreshAck.fromJson(Map<String, dynamic> json) =>
      _$CorpusRefreshAckFromJson(json);
  Map<String, dynamic> toJson() => _$CorpusRefreshAckToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class DeviceTokenAck {
  final String tokenId;
  final String status;

  DeviceTokenAck({required this.tokenId, required this.status});

  factory DeviceTokenAck.fromJson(Map<String, dynamic> json) =>
      _$DeviceTokenAckFromJson(json);
  Map<String, dynamic> toJson() => _$DeviceTokenAckToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class VoiceIntakeAck {
  final int seededCount;
  final List<String> topics;
  final List<String> namedEntities;
  final List<String> anchorPhrases;
  final String? vibeNotes;

  VoiceIntakeAck({
    required this.seededCount,
    required this.topics,
    required this.namedEntities,
    required this.anchorPhrases,
    this.vibeNotes,
  });

  factory VoiceIntakeAck.fromJson(Map<String, dynamic> json) =>
      _$VoiceIntakeAckFromJson(json);
  Map<String, dynamic> toJson() => _$VoiceIntakeAckToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class AccountDeletionAck {
  final String userId;
  final bool alreadyDeleted;
  final int audioObjectsDeleted;

  AccountDeletionAck({
    required this.userId,
    required this.alreadyDeleted,
    required this.audioObjectsDeleted,
  });

  factory AccountDeletionAck.fromJson(Map<String, dynamic> json) =>
      _$AccountDeletionAckFromJson(json);
  Map<String, dynamic> toJson() => _$AccountDeletionAckToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class AccountResetAck {
  final String userId;

  AccountResetAck({required this.userId});

  factory AccountResetAck.fromJson(Map<String, dynamic> json) =>
      _$AccountResetAckFromJson(json);
  Map<String, dynamic> toJson() => _$AccountResetAckToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class VerifySubscriptionPayload {
  final String tier;
  final String? status;
  final String? productId;
  final String? expiresAt;

  VerifySubscriptionPayload({
    required this.tier,
    this.status,
    this.productId,
    this.expiresAt,
  });

  factory VerifySubscriptionPayload.fromJson(Map<String, dynamic> json) =>
      _$VerifySubscriptionPayloadFromJson(json);
  Map<String, dynamic> toJson() => _$VerifySubscriptionPayloadToJson(this);
}

@JsonSerializable(fieldRename: FieldRename.snake)
class VerifySubscriptionEnvelope {
  final bool accepted;
  final String? eventId;
  final VerifySubscriptionPayload? subscription;

  VerifySubscriptionEnvelope({
    required this.accepted,
    this.eventId,
    this.subscription,
  });

  factory VerifySubscriptionEnvelope.fromJson(Map<String, dynamic> json) =>
      _$VerifySubscriptionEnvelopeFromJson(json);
  Map<String, dynamic> toJson() => _$VerifySubscriptionEnvelopeToJson(this);
}
