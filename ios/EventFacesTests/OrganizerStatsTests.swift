import Foundation
import Testing
@testable import EventFaces

/// `OrganizerStats.aggregate` mirrors the web dashboard's four tiles (event-admin.tsx
/// StatsRow): fixtures are decoded from JSON rather than memberwise-initialized, so the
/// test doesn't depend on the generated client's init parameter order.
@Suite("Organizer stats aggregation")
struct OrganizerStatsTests {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) -> T {
        try! JSONDecoder.api.decode(T.self, from: Data(json.utf8))
    }

    private func sync(published: Int, faces: Int) -> SyncStatusInfo {
        decode(SyncStatusInfo.self, """
        {"drive_configured": true, "in_progress": false, "pipeline": {}, \
        "published_photos": \(published), "faces": \(faces)}
        """)
    }

    private func member(status: String) -> Member {
        decode(Member.self, """
        {"user_id": "3F2504E0-4F89-11D3-9A0C-0305E82C3301", "email": "a@example.com", \
        "role": "attendee", "status": "\(status)", "joined_at": "2026-01-01T00:00:00Z"}
        """)
    }

    private func searchLogRow(matchCount: Int) -> SearchLogRow {
        decode(SearchLogRow.self, """
        {"match_count": \(matchCount), "created_at": "2026-01-01T00:00:00Z"}
        """)
    }

    private func moderationItem() -> ModerationItem {
        decode(ModerationItem.self, """
        {"id": "3F2504E0-4F89-11D3-9A0C-0305E82C3301", "index_status": "queued", \
        "face_count": 1, "created_at": "2026-01-01T00:00:00Z"}
        """)
    }

    private func report() -> ReportItem {
        decode(ReportItem.self, """
        {"id": "3F2504E0-4F89-11D3-9A0C-0305E82C3301", "photo_id": "3F2504E0-4F89-11D3-9A0C-0305E82C3301", \
        "reason": "other", "details": "", "status": "open", "created_at": "2026-01-01T00:00:00Z"}
        """)
    }

    private func removal() -> RemovalItem {
        decode(RemovalItem.self, """
        {"id": "3F2504E0-4F89-11D3-9A0C-0305E82C3301", "email": "a@example.com", "message": "", \
        "status": "submitted", "matched_photo_ids": [], "created_at": "2026-01-01T00:00:00Z"}
        """)
    }

    @Test func photosTileUsesSyncStatus() {
        let stats = OrganizerStats.aggregate(sync: sync(published: 12, faces: 30), members: nil, searchLog: nil, queue: nil, reports: nil, removals: nil)
        #expect(stats.publishedPhotos == 12 && stats.facesFound == 30)
    }

    @Test func membersTileSplitsApprovedAndPending() {
        let stats = OrganizerStats.aggregate(
            sync: nil, members: [member(status: "approved"), member(status: "approved"), member(status: "pending"), member(status: "revoked")],
            searchLog: nil, queue: nil, reports: nil, removals: nil
        )
        #expect(stats.approvedMembers == 2 && stats.pendingMembers == 1)
    }

    @Test func searchesTileComputesMatchRate() {
        let stats = OrganizerStats.aggregate(
            sync: nil, members: nil,
            searchLog: [searchLogRow(matchCount: 1), searchLogRow(matchCount: 0), searchLogRow(matchCount: 2), searchLogRow(matchCount: 0)],
            queue: nil, reports: nil, removals: nil
        )
        #expect(stats.searchCount == 4 && stats.matchRatePercent == 50)
    }

    @Test func searchesTileHasNoRateWhenThereAreNoSearches() {
        let stats = OrganizerStats.aggregate(sync: nil, members: nil, searchLog: [], queue: nil, reports: nil, removals: nil)
        #expect(stats.searchCount == 0 && stats.matchRatePercent == nil)
    }

    @Test func needsAttentionSumsQueueReportsAndRemovals() {
        let stats = OrganizerStats.aggregate(
            sync: nil, members: nil, searchLog: nil,
            queue: [moderationItem()], reports: [report(), report()], removals: [removal()]
        )
        #expect(stats.needsAttention == 4)
    }

    @Test func needsAttentionIsZeroNotNilWhenAllThreeAreEmpty() {
        let stats = OrganizerStats.aggregate(sync: nil, members: nil, searchLog: nil, queue: [], reports: [], removals: [])
        #expect(stats.needsAttention == 0)
    }

    @Test func needsAttentionStaysNilWhenEveryFetchFailed() {
        let stats = OrganizerStats.aggregate(sync: nil, members: nil, searchLog: nil, queue: nil, reports: nil, removals: nil)
        #expect(stats.needsAttention == nil)
    }

    @Test func needsAttentionCountsWhatSucceededWhenOthersFailed() {
        // queue/reports fetch failed (nil); only removals succeeded: still a real count, not "—".
        let stats = OrganizerStats.aggregate(sync: nil, members: nil, searchLog: nil, queue: nil, reports: nil, removals: [removal(), removal()])
        #expect(stats.needsAttention == 2)
    }
}
