import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../state/app_state.dart';

/// 8-step onboarding wizard (welcome → name → sources → Substack → voice →
/// schedule → weather → done) with progress dots and optimistic advance. In this
/// build the collected values are local; finishing calls completeOnboarding so
/// RootView shows the dashboard. Real persistence wires in with auth.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  static const _stepCount = 8;

  int _step = 0;
  final _nameController = TextEditingController();
  String? _voiceId;
  bool _includeWeather = false;

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  void _next() {
    if (_step < _stepCount - 1) {
      setState(() => _step++);
    } else {
      AppScope.of(context).completeOnboarding();
    }
  }

  void _back() {
    if (_step > 0) setState(() => _step--);
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final isLast = _step == _stepCount - 1;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          child: Column(
            children: [
              _dots(),
              const SizedBox(height: DesignTokens.spacingL),
              Expanded(child: _stepContent(text)),
              Row(
                children: [
                  if (_step > 0)
                    TextButton(onPressed: _back, child: const Text('Back')),
                  const Spacer(),
                  ElevatedButton(
                    onPressed: _next,
                    child: Text(isLast ? 'Finish' : 'Next'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _dots() {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: List.generate(_stepCount, (i) {
        return Container(
          margin: const EdgeInsets.symmetric(horizontal: 3),
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: i <= _step ? DesignTokens.colorAmber : DesignTokens.colorRule,
          ),
        );
      }),
    );
  }

  Widget _stepContent(TextTheme text) {
    switch (_step) {
      case 0:
        return _info(text, 'Welcome to ClawCast',
            'A daily briefing podcast, built from the sources you choose.');
      case 1:
        return _nameStep(text);
      case 2:
        return _info(text, 'Pick your sources',
            'Start from a curated catalog of tech and business newsletters — '
                'you can tune it any time.');
      case 3:
        return _info(text, 'Add your Substacks',
            'Forward Substack subscriptions to your private ClawCast address '
                'to fold them into your pod.');
      case 4:
        return _voiceStep(text);
      case 5:
        return _info(text, 'Set your schedule',
            'Choose which mornings your pod is ready. We default to weekdays '
                'at 07:00.');
      case 6:
        return _weatherStep(text);
      case 7:
        return _info(text, 'You’re all set',
            'We’ll generate your first pod shortly. You can change everything '
                'later from the app.');
      default:
        return const SizedBox.shrink();
    }
  }

  Widget _info(TextTheme text, String title, String body) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text(title, style: text.displayLarge),
        const SizedBox(height: DesignTokens.spacingM),
        Text(body, style: text.bodyMedium),
      ],
    );
  }

  Widget _nameStep(TextTheme text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text('What should we call you?', style: text.displayLarge),
        const SizedBox(height: DesignTokens.spacingM),
        TextField(
          controller: _nameController,
          decoration: const InputDecoration(labelText: 'Your name'),
        ),
      ],
    );
  }

  Widget _voiceStep(TextTheme text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text('Choose a voice', style: text.displayLarge),
        const SizedBox(height: DesignTokens.spacingM),
        DropdownButton<String?>(
          value: _voiceId,
          isExpanded: true,
          items: const [
            DropdownMenuItem<String?>(value: null, child: Text('Default')),
            DropdownMenuItem<String?>(value: 'vinnie', child: Text('Vinnie Chase')),
            DropdownMenuItem<String?>(value: 'demi', child: Text('Demi Dreams')),
          ],
          onChanged: (v) => setState(() => _voiceId = v),
        ),
      ],
    );
  }

  Widget _weatherStep(TextTheme text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Text('Add a weather note?', style: text.displayLarge),
        const SizedBox(height: DesignTokens.spacingM),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          value: _includeWeather,
          onChanged: (v) => setState(() => _includeWeather = v),
          title: const Text('Include local weather in each pod'),
        ),
      ],
    );
  }
}
