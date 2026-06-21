import Foundation

/// A `stakes` row. The dashboard picks ONE stake (the freshest the user can see) and scopes every
/// member query to it. `missionaries` is a jsonb map of unit-name → assigned missionaries.
public struct Stake: Codable, Identifiable, Hashable, Sendable {
    public let id: String
    public let name: String?
    public let unitNumber: String?
    public let lastSyncedAt: String?
    /// Coarse scrape status ("running"/"done"/…) — drives the syncing banner. Port of `sync_state`.
    public let syncState: String?
    public let syncStartedAt: String?
    public let missionaries: [String: [Missionary]]?
    public let sheetsEnabled: Bool   // #5b: whether per-stake Google Sheets are generated this run

    public enum CodingKeys: String, CodingKey {
        case id, name
        case unitNumber = "unit_number"
        case lastSyncedAt = "last_synced_at"
        case syncState = "sync_state"
        case syncStartedAt = "sync_started_at"
        case missionaries
        case sheetsEnabled = "sheets_enabled"
    }

    public init(id: String, name: String? = nil, unitNumber: String? = nil,
                lastSyncedAt: String? = nil, syncState: String? = nil, syncStartedAt: String? = nil,
                missionaries: [String: [Missionary]]? = nil, sheetsEnabled: Bool = false) {
        self.id = id; self.name = name; self.unitNumber = unitNumber
        self.lastSyncedAt = lastSyncedAt; self.syncState = syncState; self.syncStartedAt = syncStartedAt
        self.missionaries = missionaries; self.sheetsEnabled = sheetsEnabled
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name)
        // unit_number can be int or string in the DB.
        unitNumber = try c.decodeStringLoose(.unitNumber)
        lastSyncedAt = try c.decodeIfPresent(String.self, forKey: .lastSyncedAt)
        syncState = try c.decodeIfPresent(String.self, forKey: .syncState)
        syncStartedAt = try c.decodeIfPresent(String.self, forKey: .syncStartedAt)
        // missionaries may be null or an object; decode tolerantly so a malformed map never blocks
        // the stake from loading (the missionary strip is decorative).
        missionaries = (try? c.decodeIfPresent([String: [Missionary]].self, forKey: .missionaries)) ?? nil
        sheetsEnabled = (try? c.decodeIfPresent(Bool.self, forKey: .sheetsEnabled)) ?? false
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id)
        try c.encodeIfPresent(name, forKey: .name)
        try c.encodeIfPresent(unitNumber, forKey: .unitNumber)
        try c.encodeIfPresent(lastSyncedAt, forKey: .lastSyncedAt)
        try c.encodeIfPresent(syncState, forKey: .syncState)
        try c.encodeIfPresent(syncStartedAt, forKey: .syncStartedAt)
        try c.encodeIfPresent(missionaries, forKey: .missionaries)
        try c.encode(sheetsEnabled, forKey: .sheetsEnabled)
    }

    /// True if a scrape is currently running and started recently (<30 min) — guards a crashed run
    /// that never marked itself 'done'. Mirrors `_applyCurrentStake`'s running check.
    public var isSyncing: Bool {
        guard syncState == "running", let started = Freshness.parse(syncStartedAt) else { return false }
        return Date().timeIntervalSince(started) < 30 * 60
    }
}

public struct Missionary: Codable, Hashable, Sendable {
    public let name: String?
    public let phone: String?
    public let email: String?
    /// Cached avatar (a signed Supabase Storage URL re-signed each sync); nil → initials fallback.
    public let photoURL: String?
    enum CodingKeys: String, CodingKey {
        case name, phone, email
        case photoURL = "photo_url"
    }
    public init(name: String? = nil, phone: String? = nil, email: String? = nil, photoURL: String? = nil) {
        self.name = name; self.phone = phone; self.email = email; self.photoURL = photoURL
    }
}
