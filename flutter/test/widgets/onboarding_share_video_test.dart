import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/widgets/onboarding_share_video.dart';

/// The video platform plugin isn't registered in widget tests, so the
/// controller can never initialise — [OnboardingShareVideo] must render its
/// fallback (never a blank gap) and must not throw while trying to load. This
/// is the same degradation path a device hits if the asset fails to decode.
void main() {
  testWidgets('renders the fallback when the video plugin is unavailable',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: OnboardingShareVideo(
            fallback: Text('SHARE_SHEET_MOCK'),
          ),
        ),
      ),
    );
    // Let initState's initialize() future reject and get caught.
    await tester.pumpAndSettle();

    expect(find.text('SHARE_SHEET_MOCK'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
