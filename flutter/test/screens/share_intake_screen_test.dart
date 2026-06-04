import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/data/fake_app_repository.dart';
import 'package:app/screens/share_intake_screen.dart';
import 'package:app/services/share_intake_controller.dart';
import 'package:app/state/app_state.dart';

Widget _host({required List<PendingShare> shares, required VoidCallback onDone}) {
  return AppScope(
    notifier: AppState(FakeAppRepository()),
    child: MaterialApp(
      home: ShareIntakeScreen(shares: shares, onDone: onDone),
    ),
  );
}

void main() {
  testWidgets('a shared link uploads and confirms "Pinned to your next pod."',
      (tester) async {
    var done = false;
    await tester.pumpWidget(_host(
      shares: const [
        PendingShare(kind: 'url', url: 'https://example.com/a', label: 'https://example.com/a'),
      ],
      onDone: () => done = true,
    ));

    // While uploading: the "Sending…" header (and per-row note).
    await tester.pump();
    expect(find.text('Sending…'), findsWidgets);

    // Fake repository resolves after ~200ms.
    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();

    expect(find.text('Pinned to your next pod.'), findsOneWidget);
    expect(find.text('Pinned to your next pod'), findsOneWidget); // per-row note

    // Done hands control back to the caller (clears the queue).
    await tester.tap(find.text('Done'));
    await tester.pump();
    expect(done, isTrue);
  });

  testWidgets('a re-shared link is reported as already queued', (tester) async {
    await tester.pumpWidget(_host(
      shares: const [
        PendingShare(kind: 'url', url: 'https://example.com/dup', label: 'https://example.com/dup'),
        PendingShare(kind: 'url', url: 'https://example.com/dup', label: 'https://example.com/dup'),
      ],
      onDone: () {},
    ));

    await tester.pump(const Duration(milliseconds: 600));
    await tester.pumpAndSettle();

    expect(find.text('Pinned to your next pod'), findsOneWidget);
    expect(find.text('Already in your next pod'), findsOneWidget);
  });

  testWidgets('an unsupported item fails gracefully without blocking', (tester) async {
    await tester.pumpWidget(_host(
      shares: const [
        PendingShare(kind: 'unsupported', label: 'photo.jpg'),
      ],
      onDone: () {},
    ));

    await tester.pump(const Duration(milliseconds: 400));
    await tester.pumpAndSettle();

    expect(find.textContaining("can't be sent to ClawCast"), findsOneWidget);
    expect(find.text('Done'), findsOneWidget);
  });
}
