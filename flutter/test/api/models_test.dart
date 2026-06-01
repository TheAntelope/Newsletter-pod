import 'package:flutter_test/flutter_test.dart';

import 'package:app/api/models.dart';

void main() {
  group('UserDto', () {
    test('maps snake_case keys and round-trips', () {
      final user = UserDto.fromJson({
        'id': 'u1',
        'email': 'a@b.com',
        'display_name': 'Vince Martin',
        'timezone': 'UTC',
        'inbound_address': 'x@theclawcast.com',
      });
      expect(user.id, 'u1');
      expect(user.displayName, 'Vince Martin');
      expect(user.inboundAddress, 'x@theclawcast.com');
      expect(user.hasFriendlyName, isTrue);
      expect(user.firstName, 'Vince');
      // toJson emits snake_case again.
      expect(user.toJson()['display_name'], 'Vince Martin');
    });

    test('treats email-prefix-like and Listener names as not friendly', () {
      final bot = UserDto.fromJson(
        {'id': 'u2', 'display_name': '6hk6266a', 'timezone': 'UTC'},
      );
      expect(bot.hasFriendlyName, isFalse);
      expect(bot.firstName, '');

      final listener = UserDto.fromJson(
        {'id': 'u3', 'display_name': 'Listener', 'timezone': 'UTC'},
      );
      expect(listener.hasFriendlyName, isFalse);
    });
  });

  test('SessionEnvelope decodes nested DTOs', () {
    final env = SessionEnvelope.fromJson({
      'session_token': 'tok',
      'is_new_user': true,
      'user': {'id': 'u1', 'display_name': 'A', 'timezone': 'UTC'},
      'subscription': {
        'user_id': 'u1',
        'tier': 'free',
        'status': 'active',
      },
    });
    expect(env.sessionToken, 'tok');
    expect(env.isNewUser, isTrue);
    expect(env.user.id, 'u1');
    expect(env.subscription.tier, 'free');
  });

  group('EntitlementsDto tolerant defaults', () {
    Map<String, dynamic> base() => {
          'tier': 'free',
          'max_delivery_days': 7,
          'min_duration_minutes': 3,
          'max_duration_minutes': 5,
          'max_items_per_episode': 25,
        };

    test('absent quota fields default to 0/false/null', () {
      final ent = EntitlementsDto.fromJson(base());
      expect(ent.premiumPodsPerWeek, 0);
      expect(ent.defaultPodsRemainingThisWeek, 0);
      expect(ent.isInTrial, isFalse);
      expect(ent.isInFirstMonth, isFalse);
      expect(ent.firstMonthEndsAt, isNull);
    });

    test('present quota fields are parsed', () {
      final ent = EntitlementsDto.fromJson({
        ...base(),
        'premium_pods_per_week': 3,
        'is_in_trial': true,
        'first_month_ends_at': '2026-07-01T00:00:00Z',
      });
      expect(ent.premiumPodsPerWeek, 3);
      expect(ent.isInTrial, isTrue);
      expect(ent.firstMonthEndsAt, isNotNull);
    });
  });

  group('SubstackIntentDto', () {
    Map<String, dynamic> base(String status) => {
          'id': 'i1',
          'user_id': 'u1',
          'pub_url': 'https://x.substack.com',
          'pub_host': 'x.substack.com',
          'has_paid_tier': false,
          'alias_email': 'a@theclawcast.com',
          'created_at': '2026-06-01T00:00:00Z',
          'status': status,
        };

    test('maps the enum and collapses autoConfirmed to pending for display', () {
      final intent = SubstackIntentDto.fromJson(base('auto_confirmed'));
      expect(intent.status, SubstackIntentStatus.autoConfirmed);
      expect(intent.displayStatus, SubstackIntentStatus.pending);
      expect(intent.subscribeUrl.toString(), 'https://x.substack.com/subscribe');
      expect(intent.hasLiveVerificationCode, isFalse);
    });

    test('hasLiveVerificationCode reflects an unexpired code', () {
      final future =
          DateTime.now().toUtc().add(const Duration(hours: 1)).toIso8601String();
      final intent = SubstackIntentDto.fromJson({
        ...base('pending'),
        'pending_verification_code': '123456',
        'pending_verification_expires_at': future,
      });
      expect(intent.hasLiveVerificationCode, isTrue);
    });
  });

  test('NextEpisodeCandidateDto defaults shared to false', () {
    final cand = NextEpisodeCandidateDto.fromJson({
      'dedupe_key': 'd1',
      'source_id': 's1',
      'source_name': 'Src',
      'title': 'T',
      'summary': 'S',
      'link': 'https://x',
      'published_at': '2026-06-01T00:00:00Z',
      'pinned': false,
      'likely_included': true,
    });
    expect(cand.dedupeKey, 'd1');
    expect(cand.likelyIncluded, isTrue);
    expect(cand.shared, isFalse);
  });

  group('SwipeDeckCardDto.displaySummary', () {
    Map<String, dynamic> base() => {
          'source_item_dedupe_key': 'k',
          'title': 'T',
          'summary': '<p>Hello   <b>world</b></p>',
          'source_id': 's',
          'source_name': 'n',
          'link': 'https://x',
          'published_at': '2026-06-01T00:00:00Z',
        };

    test('strips HTML and collapses whitespace when no card summary', () {
      final card = SwipeDeckCardDto.fromJson(base());
      expect(card.displaySummary, 'Hello world');
    });

    test('prefers the LLM card summary when present', () {
      final card =
          SwipeDeckCardDto.fromJson({...base(), 'card_summary': 'Nice brief'});
      expect(card.displaySummary, 'Nice brief');
    });
  });
}
