import 'package:flutter/material.dart';

import '../api/hermes_api.dart';
import '../theme/hermes_palette.dart';
import '../widgets/hermes_shell.dart';
import '../widgets/markdown_body.dart';
import '../widgets/profile_ui.dart';

class LegalDocumentScreen extends StatefulWidget {
  const LegalDocumentScreen({
    super.key,
    required this.doc,
    required this.title,
    required this.api,
  });

  final String doc;
  final String title;
  final HermesApi api;

  @override
  State<LegalDocumentScreen> createState() => _LegalDocumentScreenState();
}

class _LegalDocumentScreenState extends State<LegalDocumentScreen> {
  String? _markdown;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final text = await widget.api.fetchLegalDocument(widget.doc);
      if (mounted) setState(() => _markdown = text);
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = HermesPalette.of(context);
    return Scaffold(
      backgroundColor: p.background,
      appBar: AppBar(
        title: Text(widget.title),
        backgroundColor: p.background,
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Text(_error!, textAlign: TextAlign.center),
                        const SizedBox(height: 16),
                        FilledButton(onPressed: _load, child: const Text('重试')),
                      ],
                    ),
                  ),
                )
              : ListView(
                  padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
                  children: [
                    HermesSolidCard(
                      padding: const EdgeInsets.all(20),
                      child: HermesMarkdownBody(data: _markdown ?? ''),
                    ),
                  ],
                ),
    );
  }
}
