import XCTest
@testable import CovenantPathKit

/// Verifies the Codable mappings match the Supabase column names from the spec's select string, and
/// that the tolerant `details` decoders handle partial / mixed-type JSON without throwing.
final class DecodingTests: XCTestCase {

    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        try JSONDecoder().decode(T.self, from: Data(json.utf8))
    }

    func testMemberSnakeCaseMapping() throws {
        let json = """
        {
          "person_uuid": "abc-123",
          "stake_id": "stake-1",
          "unit_id": "unit-9",
          "name": "Doe, Jane",
          "unit_name": "First Ward",
          "baptism_date": "2026-02-06",
          "baptism_goal_date": null,
          "birth_date": "1990-05-01",
          "membership_duration": "Member for 8 months",
          "sex": "F",
          "friends": "Yes",
          "aaronic_priesthood": "N/A",
          "melchizedek_priesthood": "No",
          "calling": "Yes",
          "ministering_brothers_sisters": "Yes",
          "ministering_assignment": "No",
          "temple_recommend": "Active",
          "patriarchal_blessing": "No",
          "living_ordinance": "No",
          "kind": "new_member",
          "photo_url": null,
          "details": null
        }
        """
        let m = try decode(Member.self, json)
        XCTAssertEqual(m.personUUID, "abc-123")
        XCTAssertEqual(m.stakeID, "stake-1")
        XCTAssertEqual(m.unitName, "First Ward")
        XCTAssertEqual(m.baptismDate, "2026-02-06")
        XCTAssertEqual(m.friends, "Yes")
        XCTAssertEqual(m.aaronicPriesthood, "N/A")
        XCTAssertEqual(m.kind, "new_member")
        XCTAssertFalse(m.isInvestigator)
        XCTAssertEqual(m.displayName, "Doe, Jane")
        XCTAssertNil(m.details)
    }

    func testDetailsTolerantDecode() throws {
        // taughtLevel as a NUMBER, ministering names as plain strings, a partial subtree.
        let json = """
        {
          "memberSince": "Member for 1 year",
          "sacramentMissed": 2,
          "friends": [{"name": "A", "unit": "First Ward", "inStake": true}],
          "ministeringBrothers": ["Bro One", "Bro Two"],
          "sacrament": [{"label": "Feb 2", "attended": true, "date": "2026-02-02"}],
          "lessons": [{"name": "Faith", "principles": [
              {"name": "Repentance", "memberPresent": true, "taughtLevel": 1},
              {"name": "Baptism", "memberPresent": false, "taughtLevel": "0"}
          ]}],
          "callings": ["Sunday School Teacher"],
          "templeExperiences": [{"name": "Baptisms for the dead", "done": true}],
          "tags": ["Recent convert"]
        }
        """
        let d = try decode(MemberDetails.self, json)
        XCTAssertEqual(d.memberSince, "Member for 1 year")
        XCTAssertEqual(d.sacramentMissed, 2)
        XCTAssertEqual(d.friends?.first?.unit, "First Ward")
        XCTAssertEqual(d.friends?.first?.inStake, true)
        XCTAssertEqual(d.ministeringBrothers, ["Bro One", "Bro Two"])
        XCTAssertEqual(d.sacrament?.first?.attended, true)
        let principles = d.lessons?.first?.principles ?? []
        XCTAssertEqual(principles.count, 2)
        XCTAssertTrue(principles[0].isTaught)        // taughtLevel 1 → taught
        XCTAssertFalse(principles[1].isTaught)       // taughtLevel "0" → not taught
        XCTAssertEqual(d.callings, ["Sunday School Teacher"])
        XCTAssertEqual(d.templeExperiences?.first?.done, true)
        XCTAssertEqual(d.tags, ["Recent convert"])
    }

    func testMinisteringNamesAsObjects() throws {
        // The spec also documents the object form [{name}] — accept it too.
        let json = """
        { "ministeringSisters": [{"name": "Sister X"}, {"name": "Sister Y"}] }
        """
        let d = try decode(MemberDetails.self, json)
        XCTAssertEqual(d.ministeringSisters, ["Sister X", "Sister Y"])
    }

    func testStakeDecodeWithMissionaries() throws {
        let json = """
        {
          "id": "stake-1",
          "name": "Provo Stake",
          "unit_number": 12345,
          "last_synced_at": "2026-05-30T12:00:00Z",
          "missionaries": {
            "First Ward": [{"name": "Elder A", "phone": "555-1234", "email": "a@x.org"}]
          }
        }
        """
        let s = try decode(Stake.self, json)
        XCTAssertEqual(s.id, "stake-1")
        XCTAssertEqual(s.name, "Provo Stake")
        XCTAssertEqual(s.unitNumber, "12345")   // int coerced to string
        XCTAssertEqual(s.missionaries?["First Ward"]?.first?.name, "Elder A")
    }

    func testInvestigatorKind() throws {
        let m = try decode(Member.self, #"{"name":"X","kind":"investigator","baptism_goal_date":"2026-07-01"}"#)
        XCTAssertTrue(m.isInvestigator)
        XCTAssertEqual(m.baptismGoalDate, "2026-07-01")
    }
}
