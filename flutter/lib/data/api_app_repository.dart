import '../api/api_client.dart';
import '../api/models.dart';
import 'app_repository.dart';

/// Production repository: wraps [ApiClient] with the signed-in session token.
class ApiAppRepository implements AppRepository {
  ApiAppRepository(this._client, this._token);

  final ApiClient _client;
  final String _token;

  @override
  Future<MeEnvelope> fetchMe() => _client.fetchMe(_token);

  @override
  Future<RunStartEnvelope> generateNow() => _client.generateNow(_token);
}
