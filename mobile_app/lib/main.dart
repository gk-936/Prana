import 'package:flutter/material.dart';

import 'screens/dashboard_screen.dart';
import 'screens/onboarding_screen.dart';
import 'services/api_client.dart';

void main() {
  runApp(const PranaApp());
}

class PranaApp extends StatelessWidget {
  const PranaApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'PRANA',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF147D64),
          brightness: Brightness.light,
        ),
        inputDecorationTheme: const InputDecorationTheme(
          border: OutlineInputBorder(),
          isDense: true,
        ),
        useMaterial3: true,
      ),
      home: const _RootRouter(),
    );
  }
}

class _RootRouter extends StatefulWidget {
  const _RootRouter();

  @override
  State<_RootRouter> createState() => _RootRouterState();
}

class _RootRouterState extends State<_RootRouter> {
  static const _baseUrl = 'http://10.0.2.2:8000';
  late final PranaApiClient _apiClient = PranaApiClient(baseUrl: _baseUrl);
  bool _showDashboard = false;

  @override
  Widget build(BuildContext context) {
    if (_showDashboard) {
      return DashboardScreen(apiClient: _apiClient);
    }
    return OnboardingScreen(
      apiClient: _apiClient,
      onContinue: () => setState(() => _showDashboard = true),
    );
  }
}
