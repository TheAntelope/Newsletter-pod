import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

class SourcesScreen extends StatefulWidget {
  const SourcesScreen({super.key});

  @override
  State<SourcesScreen> createState() => _SourcesScreenState();
}

class _SourcesScreenState extends State<SourcesScreen> {
  Future<SourcesEnvelope>? _future;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _future ??= AppScope.of(context).repository.fetchSources();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Sources')),
      body: SafeArea(
        child: FutureBuilder<SourcesEnvelope>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: Text('${snapshot.error}'));
            }
            final sources = snapshot.data!.sources;
            return ListView.separated(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              itemCount: sources.length,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: DesignTokens.spacingS),
              itemBuilder: (context, i) {
                final s = sources[i];
                return Card(
                  child: ListTile(
                    title: Text(s.name, style: text.titleMedium),
                    subtitle: Text(
                      s.isCustom ? 'Custom feed' : 'Curated',
                      style: text.labelMedium
                          ?.copyWith(color: DesignTokens.colorMuted),
                    ),
                    trailing: Icon(
                      s.enabled ? Icons.check_circle : Icons.circle_outlined,
                      color: s.enabled
                          ? DesignTokens.colorAmber
                          : DesignTokens.colorMuted,
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
