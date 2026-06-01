import 'package:flutter_test/flutter_test.dart';

import 'package:app/data/fake_app_repository.dart';
import 'package:app/main.dart';
import 'package:app/state/app_state.dart';

void main() {
  testWidgets('stub sign-in routes to the dashboard with the user', (tester) async {
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    // Sign-in screen first.
    expect(find.text('ClawCast'), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    // Dashboard renders the demo user and the generate action.
    expect(find.textContaining('Vince'), findsWidgets);
    expect(find.text('Generate now'), findsOneWidget);

    // Generating surfaces the run message.
    await tester.tap(find.text('Generate now'));
    await tester.pumpAndSettle();
    expect(find.textContaining('being generated'), findsOneWidget);
  });
}
