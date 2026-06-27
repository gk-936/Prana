import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:prana_app/screens/dashboard_screen.dart';
import 'package:prana_app/services/api_client.dart';

void main() {
  testWidgets('dashboard renders core controls', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: DashboardScreen(
          apiClient: PranaApiClient(baseUrl: 'http://10.0.2.2:8000'),
        ),
      ),
    );

    expect(find.text('PRANA'), findsOneWidget);
    expect(find.text('Location'), findsOneWidget);
    expect(find.text('Use GPS'), findsOneWidget);
    expect(find.text('Calculate'), findsOneWidget);
    expect(find.text('Live PRANA results will appear here.'), findsOneWidget);
  });
}
