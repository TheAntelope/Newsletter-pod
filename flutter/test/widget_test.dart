import 'package:flutter_test/flutter_test.dart';

import 'package:app/main.dart';

void main() {
  testWidgets('Home renders the ClawCast wordmark and tagline', (tester) async {
    await tester.pumpWidget(const ClawcastApp());

    expect(find.text('ClawCast'), findsOneWidget);
    expect(find.text('Your briefing, in your ears.'), findsOneWidget);
  });
}
