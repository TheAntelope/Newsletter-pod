import 'package:flutter_test/flutter_test.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';

import 'package:app/services/share_intake_controller.dart';

void main() {
  group('classifyText', () {
    test('a bare https link is promoted to a url share', () {
      final share = ShareIntakeController.classifyText('  https://example.com/a  ');
      expect(share.kind, 'url');
      expect(share.url, 'https://example.com/a');
    });

    test('plain prose stays a text share', () {
      final share = ShareIntakeController.classifyText('read this great thing');
      expect(share.kind, 'text');
      expect(share.text, 'read this great thing');
    });

    test('text containing a url (not bare) stays text', () {
      final share = ShareIntakeController.classifyText('cool: https://example.com');
      expect(share.kind, 'text');
    });
  });

  group('mapSharedFile', () {
    SharedMediaFile file(SharedMediaType type, String path, {String? mime}) =>
        SharedMediaFile(path: path, type: type, mimeType: mime);

    test('a url type maps straight to a url share', () {
      final share = ShareIntakeController.mapSharedFile(
          file(SharedMediaType.url, 'https://example.com/x'));
      expect(share.kind, 'url');
      expect(share.url, 'https://example.com/x');
    });

    test('a pdf file maps to kind=pdf with its path', () {
      final share = ShareIntakeController.mapSharedFile(
          file(SharedMediaType.file, '/tmp/report.pdf', mime: 'application/pdf'));
      expect(share.kind, 'pdf');
      expect(share.filePath, '/tmp/report.pdf');
      expect(share.fileName, 'report.pdf');
    });

    test('epub + docx are recognized by extension', () {
      expect(
        ShareIntakeController.mapSharedFile(
                file(SharedMediaType.file, '/tmp/book.epub'))
            .kind,
        'epub',
      );
      expect(
        ShareIntakeController.mapSharedFile(
                file(SharedMediaType.file, '/tmp/memo.docx'))
            .kind,
        'docx',
      );
    });

    test('an unknown file type is marked unsupported', () {
      final share = ShareIntakeController.mapSharedFile(
          file(SharedMediaType.file, '/tmp/sheet.xlsx'));
      expect(share.supported, isFalse);
    });

    test('images are unsupported', () {
      final share = ShareIntakeController.mapSharedFile(
          file(SharedMediaType.image, '/tmp/pic.jpg'));
      expect(share.supported, isFalse);
    });
  });
}
