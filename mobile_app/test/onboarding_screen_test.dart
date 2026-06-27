// mobile_app/test/onboarding_screen_test.dart

import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:prana_app/screens/onboarding_screen.dart';
import 'package:prana_app/services/api_client.dart';

class _FakeHttpClient extends http.BaseClient {
  _FakeHttpClient(this.responseBody, this.statusCode);

  final String responseBody;
  final int statusCode;
  http.Request? lastRequest;
  List<int>? lastBodyBytes;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) async {
    if (request is http.Request) {
      lastRequest = request;
      lastBodyBytes = request.bodyBytes;
    }
    final bytes = utf8.encode(responseBody);
    return http.StreamedResponse(Stream.value(bytes), statusCode);
  }
}

void main() {
  testWidgets('submitting the form calls register with the entered values', (
    WidgetTester tester,
  ) async {
    final fakeClient = _FakeHttpClient(
      jsonEncode({
        'ok': true,
        'user_id': '+919900001111',
        'verified': false,
        'whatsapp_link': 'https://wa.me/919900000000?text=PRANA%20START',
      }),
      200,
    );
    final apiClient = PranaApiClient(
      baseUrl: 'http://10.0.2.2:8000',
      client: fakeClient,
    );

    await tester.pumpWidget(
      MaterialApp(
        home: OnboardingScreen(apiClient: apiClient, onContinue: () {}),
      ),
    );

    await tester.enterText(find.byKey(const Key('phoneField')), '+919900001111');
    await tester.enterText(
      find.byKey(const Key('locationNameField')),
      'T. Nagar, Chennai',
    );
    await tester.enterText(find.byKey(const Key('latField')), '13.0827');
    await tester.enterText(find.byKey(const Key('lonField')), '80.2707');

    await tester.tap(find.byKey(const Key('registerButton')));
    await tester.pumpAndSettle();

    expect(fakeClient.lastRequest, isNotNull);
    final sentBody =
        jsonDecode(utf8.decode(fakeClient.lastBodyBytes!)) as Map<String, dynamic>;
    expect(sentBody['phone'], '+919900001111');
    expect(sentBody['location_name'], 'T. Nagar, Chennai');
    expect(sentBody['lat'], 13.0827);
    expect(sentBody['lon'], 80.2707);
    expect(sentBody['onboarding']['ac'], false);
    expect(sentBody['onboarding']['roof_material'], 'concrete');
    expect(sentBody['onboarding']['floor_level'], 'ground');

    expect(find.text('Open WhatsApp'), findsOneWidget);
    expect(find.text('Continue to Dashboard'), findsOneWidget);
  });
}
