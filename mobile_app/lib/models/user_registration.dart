class HomeProfile {
  HomeProfile({
    required this.ac,
    required this.roofMaterial,
    required this.floorLevel,
    this.fan = false,
    this.windowsOpen = false,
    this.occupants = 1,
  });

  final bool ac;
  final String roofMaterial;
  final String floorLevel;
  final bool fan;
  final bool windowsOpen;
  final int occupants;

  Map<String, dynamic> toJson() => {
    'ac': ac,
    'roof_material': roofMaterial,
    'floor_level': floorLevel,
    'fan': fan,
    'windows_open': windowsOpen,
    'occupants': occupants,
  };

  factory HomeProfile.fromJson(Map<String, dynamic> json) => HomeProfile(
    ac: json['ac'] as bool? ?? false,
    roofMaterial: json['roof_material'] as String? ?? 'concrete',
    floorLevel: json['floor_level'] as String? ?? 'ground',
    fan: json['fan'] as bool? ?? false,
    windowsOpen: json['windows_open'] as bool? ?? false,
    occupants: (json['occupants'] as num?)?.toInt() ?? 1,
  );
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
    required this.sandboxJoinCode,
  });

  factory RegisterResult.fromJson(Map<String, dynamic> json) {
    return RegisterResult(
      ok: json['ok'] as bool,
      userId: json['user_id'] as String,
      verified: json['verified'] as bool,
      whatsappLink: json['whatsapp_link'] as String,
      sandboxJoinCode: json['sandbox_join_code'] as String,
    );
  }

  final bool ok;
  final String userId;
  final bool verified;
  final String whatsappLink;
  final String sandboxJoinCode;
}
