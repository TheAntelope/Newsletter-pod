import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/api/models.dart';
import 'package:app/data/fake_app_repository.dart';
import 'package:app/screens/account_screen.dart';
import 'package:app/state/app_state.dart';

/// A fake that records the last updateProfile call so the widget test can assert
/// the Account name-edit dialog persists the new name via the repository.
class _RecordingRepository extends FakeAppRepository {
  String? lastDisplayName;
  String? lastTimezone;

  @override
  Future<MeEnvelope> updateProfile({
    required String displayName,
    required String timezone,
  }) {
    lastDisplayName = displayName;
    lastTimezone = timezone;
    return super.updateProfile(displayName: displayName, timezone: timezone);
  }
}

void main() {
  // `testWidgets` runs inside a fake-async zone, so the FakeAppRepository's
  // `Future.delayed` calls only resolve when the tester pumps the fake clock —
  // never `await` a repository call directly here; kick it (unawaited) and pump.
  // The edit dialog's focused TextField blinks its cursor forever, so we pump
  // bounded durations rather than `pumpAndSettle` (which would never return).

  testWidgets('editing the name calls updateProfile with the new value',
      (tester) async {
    final repo = _RecordingRepository();
    final app = AppState(repo);

    await tester.pumpWidget(
      AppScope(
        notifier: app,
        child: const MaterialApp(home: AccountScreen()),
      ),
    );
    // Seed `me` so the identity card renders with the current name.
    unawaited(app.loadMe());
    await tester.pump(const Duration(milliseconds: 300));

    // Open the name-edit dialog via the "Name" card.
    await tester.tap(find.text('Edit'));
    await tester.pump(const Duration(milliseconds: 300)); // dialog open

    // Replace the prefilled name and Save.
    await tester.enterText(find.byType(TextField), 'Sophie');
    await tester.pump();
    await tester.tap(find.text('Save'));
    await tester.pump(const Duration(milliseconds: 500)); // PATCH + loadMe settle

    expect(repo.lastDisplayName, 'Sophie');
    // `me` reloaded -> identity card reflects the new name.
    expect(app.me?.user.displayName, 'Sophie');
    expect(find.text('Sophie'), findsOneWidget);
  });

  testWidgets('blank input does not call updateProfile', (tester) async {
    final repo = _RecordingRepository();
    final app = AppState(repo);

    await tester.pumpWidget(
      AppScope(
        notifier: app,
        child: const MaterialApp(home: AccountScreen()),
      ),
    );
    unawaited(app.loadMe());
    await tester.pump(const Duration(milliseconds: 300));

    await tester.tap(find.text('Edit'));
    await tester.pump(const Duration(milliseconds: 300));

    await tester.enterText(find.byType(TextField), '   ');
    await tester.pump();
    await tester.tap(find.text('Save'));
    await tester.pump(const Duration(milliseconds: 500));

    expect(repo.lastDisplayName, isNull,
        reason: 'blank input must never overwrite the existing name');
  });
}
