import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/user_registration.dart';

class PranaApiClient {
  PranaApiClient({required this.baseUrl, http.Client? client})
    : _client = client ?? http.Client();

  final String baseUrl;
  final http.Client _client;

  Future<RegisterResult> register(RegistrationRequest req) async {
    final uri = Uri.parse('$baseUrl/register');
    final response = await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(req.toJson()),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Registration failed ${response.statusCode}: ${response.body}');
    }

    return RegisterResult.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  Future<Map<String, dynamic>> getCurrentRisk({
    required double lat,
    required double lon,
    required String locationName,
    double? urbanHeatOffset,
  }) async {
    final uri = Uri.parse('$baseUrl/risk/current');
    final response = await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'lat': lat,
        'lon': lon,
        'location_name': locationName,
        'urban_heat_offset': urbanHeatOffset,
      }),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return decoded['result'] as Map<String, dynamic>;
  }
}
