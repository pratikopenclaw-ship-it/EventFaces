import Foundation
import Testing
@testable import EventFaces

@Suite("Deep links")
struct DeepLinkTests {
    let host = "eventfaces.example"
    func parse(_ s: String) -> DeepLink? { DeepLink.parse(URL(string: s)!, allowedHost: host) }

    @Test func joinWithAndWithoutCode() {
        #expect(parse("https://eventfaces.example/join/summer-party-2u6m7p?code=URPHP25E") == .join(slug: "summer-party-2u6m7p", code: "URPHP25E"))
        #expect(parse("https://eventfaces.example/join/summer-party") == .join(slug: "summer-party", code: nil))
    }

    @Test func inviteSignInAndEvent() {
        let t = "abcdefghijklmnopqrstuvwxyz_-0123"
        #expect(parse("https://eventfaces.example/invite/\(t)") == .invite(token: t))
        #expect(parse("https://eventfaces.example/m/signin?t=\(t)") == .signIn(token: t))
        #expect(parse("https://eventfaces.example/events/3F2504E0-4F89-11D3-9A0C-0305E82C3301") == .event(id: UUID(uuidString: "3F2504E0-4F89-11D3-9A0C-0305E82C3301")!))
    }

    @Test(arguments: [
        "https://evil.example/join/party",                       // other host
        "https://eventfaces.example.evil.com/join/party",        // suffix trick
        "https://evil.example@eventfaces.example/join/party",    // userinfo
        "https://user:pw@eventfaces.example/join/party",
        "http://eventfaces.example/join/party",                  // not https
        "ftp://eventfaces.example/join/party",
        "eventfaces://join/party",                               // custom scheme
        "https://eventfaces.example:8443/join/party",            // port
        "https://eventfaces.example/join/../admin/events",       // dot segments
        "https://eventfaces.example/join/a%2Fb",                 // encoded slash
        "https://eventfaces.example//join/party",
        "https://eventfaces.example/join/Party_Upper",           // slug charset
        "https://eventfaces.example/join/party?code=abc%3Cscript%3E",
        "https://eventfaces.example/join/party/extra",
        "https://eventfaces.example/admin/events/x",              // excluded on the web too
        "https://eventfaces.example/api/me",
        "https://eventfaces.example/m/signin",                   // no token
        "https://eventfaces.example/m/signin?t=short",
        "https://eventfaces.example/m/signin?t=../../etc/passwd/aaaaaaaaaaaa",
        "https://eventfaces.example/invite/tooshort",
        "https://eventfaces.example/events/not-a-uuid",
        "https://eventfaces.example/events/3F2504E04F8911D39A0C0305E82C3301",
    ])
    func rejectsTamperedLinks(_ s: String) {
        #expect(parse(s) == nil, "\(s)")
    }

    @Test func hostMatchIsCaseInsensitive() {
        #expect(parse("https://EventFaces.Example/join/party") == .join(slug: "party", code: nil))
    }

    @Test func localhostIsAllowedOverHTTPInDebugOnly() {
        let link = DeepLink.parse(URL(string: "http://localhost/join/party")!, allowedHost: "localhost")
        #if DEBUG
        #expect(link == .join(slug: "party", code: nil))
        #else
        #expect(link == nil)
        #endif
    }
}
