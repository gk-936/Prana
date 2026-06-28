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
    HomeProfile? onboarding,
    Map<String, dynamic>? sleepCheckin,
    String? userId,
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
        // Forward the saved home profile so RDS personalises the score.
        // The backend treats a null onboarding_data as "no offset".
        'onboarding_data': onboarding?.toJson(),
        'sleep_checkin': sleepCheckin,
        // When present, the backend personalises RDS from this user's stored
        // sleep check-ins (Bayesian shrinkage from the onboarding prior).
        'user_id': userId,
      }),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Backend error ${response.statusCode}: ${response.body}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return decoded['result'] as Map<String, dynamic>;
  }

  /// Record a nightly sleep check-in. These accumulate as the evidence the
  /// backend uses to personalise a user's RDS indoor-offset over time.
  ///
  /// [sleepQuality] is one of: 'good', 'moderate', 'poor'.
  /// Returns the total number of check-ins stored for the user.
  Future<int> recordCheckin({
    required String userId,
    required String sleepQuality,
    double? outdoorTemp,
    double? humidity,
    String? checkinDate,
  }) async {
    final uri = Uri.parse('$baseUrl/checkin');
    final response = await _client.post(
      uri,
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'user_id': userId,
        'sleep_quality': sleepQuality,
        'outdoor_temp': outdoorTemp,
        'humidity': humidity,
        'checkin_date': checkinDate,
      }),
    );

    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw Exception('Check-in failed ${response.statusCode}: ${response.body}');
    }

    final decoded = jsonDecode(response.body) as Map<String, dynamic>;
    return (decoded['n_checkins'] as num?)?.toInt() ?? 0;
  }
}
