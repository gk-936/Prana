class HomeProfile {
  HomeProfile({
    required this.ac,
    required this.roofMaterial,
    required this.floorLevel,
  });

  final bool ac;
  final String roofMaterial;
  final String floorLevel;

  Map<String, dynamic> toJson() => {
    'ac': ac,
    'roof_material': roofMaterial,
    'floor_level': floorLevel,
  };
}

class RegistrationRequest {
  RegistrationRequest({
    required this.phone,
    required this.locationName,
    required this.lat,
    required this.lon,
    required this.urbanHeatOffset,
    required this.onboarding,
  });

  final String phone;
  final String locationName;
  final double lat;
  final double lon;
  final double? urbanHeatOffset;
  final HomeProfile onboarding;

  Map<String, dynamic> toJson() => {
    'phone': phone,
    'location_name': locationName,
    'lat': lat,
    'lon': lon,
    'urban_heat_offset': urbanHeatOffset,
    'onboarding': onboarding.toJson(),
  };
}

class RegisterResult {
  RegisterResult({
    required this.ok,
    required this.userId,
    required this.verified,
    required this.whatsappLink,
  });

  factory RegisterResult.fromJson(Map<String, dynamic> json) {
    return RegisterResult(
      ok: json['ok'] as bool,
      userId: json['user_id'] as String,
      verified: json['verified'] as bool,
      whatsappLink: json['whatsapp_link'] as String,
    );
  }

  final bool ok;
  final String userId;
  final bool verified;
  final String whatsappLink;
}
