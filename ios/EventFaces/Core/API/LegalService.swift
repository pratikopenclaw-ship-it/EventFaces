import Foundation
import OpenAPIRuntime

typealias LegalDocument = Components.Schemas.LegalDocumentOut

/// The legal documents, served (and versioned) by the API: the same texts as on the web.
enum LegalDocumentKind: String, Sendable, Equatable, CaseIterable, Identifiable {
    case terms
    case organizerTerms = "organizer-terms"
    case privacy
    case imprint

    var id: String { rawValue }
}

extension AuthService {
    /// `language` nil: the server picks from the device languages (German or English).
    func legalDocument(_ kind: LegalDocumentKind, language: String? = nil) async throws -> LegalDocument {
        let lang = language.flatMap(Operations.LegalGetDocument.Input.Query.LangPayload.init(rawValue:))
        let document = Operations.LegalGetDocument.Input.Path.DocumentPayload(rawValue: kind.rawValue)!
        switch try await unwrappedCall({ try await publicAPI.legalGetDocument(path: .init(document: document), query: .init(lang: lang)) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw Self.error(status)
        }
    }

    /// Accept the version the user was shown. 409: it changed meanwhile (show it again).
    func acceptLegal(_ kind: LegalDocumentKind, version: String) async throws -> User {
        guard let document = Components.Schemas.AcceptLegalIn.DocumentPayload(rawValue: kind.rawValue) else { throw AppError.server(status: 422) }
        switch try await unwrappedCall({ try await api.legalAcceptDocument(body: .json(.init(document: document, version: version))) }) {
        case let .ok(ok): return try ok.body.json
        case .unprocessableContent: throw AppError.server(status: 422)
        case let .undocumented(status, _): throw status == 409 ? AppError.legalChanged : Self.error(status)
        }
    }

    private func unwrappedCall<T>(_ call: () async throws -> T) async throws -> T {
        do { return try await call() } catch let error as ClientError { throw error.underlyingError }
    }
}
