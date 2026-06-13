#if canImport(UIKit)
import SwiftUI

/// Full covenant-path detail for one member, laid out like LCR's "new member" record. Driven by
/// `member.details` (the rich subtree); when that's nil it falls back to the flat fields so the page
/// still renders. Faithful port of `person_detail_page.dart`.
struct PersonDetailView: View {
    let member: Member

    private var d: MemberDetails? { member.details }

    private var baptismLine: String? {
        if member.isInvestigator {
            let goal = member.baptismGoalDate ?? ""
            return goal.isEmpty ? nil : "Planned baptism \(goal)"
        } else {
            let b = member.baptismDate ?? ""
            return (b.isEmpty || b == "needs-profile-api") ? nil : "Baptized \(b)"
        }
    }

    private var memberSince: String? {
        d?.memberSince ?? member.membershipDuration
    }

    private var demographics: String? {
        let sex = member.sex == "M" ? "Male" : (member.sex == "F" ? "Female" : "")
        let age = Milestones.ageLabel(member) ?? ""
        let parts = [sex, age].filter { !$0.isEmpty }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                header
                // Our covenant-path milestones (data LCR's view lacks). The leading glyph is a
                // completion RING that fills with eligible-only progress and goes green at 100%.
                SectionCard(title: "Covenant Path",
                            leading: AnyView(CompletionRing(pct: Milestones.completionOf(member)))) {
                    GoldenHourChips(member: member, highlightNext: true, labeled: true)
                }
                // Each tracked status that lacks its own rich section, as its own card (eligibility-
                // gated). Renders with or without `d`.
                StatusSections(member: member)
                if let d {
                    richBody(d)
                }
                CommentsSection(member: member)
            }
            .padding(16)
            .frame(maxWidth: 1000)
            .frame(maxWidth: .infinity)
        }
        .navigationTitle(member.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            // /mlt = Member List Tool app: renders the person's covenant-path / "new member"
            // record. The bare /records/member-profile/{uuid} path is a raw RSC data route the
            // browser downloads instead of showing — hence the /mlt prefix.
            if let uuid = member.personUUID, !uuid.isEmpty,
               let url = URL(string: "https://lcr.churchofjesuschrist.org/mlt/records/member-profile/\(uuid)?lang=eng") {
                ToolbarItem(placement: .topBarTrailing) {
                    Link(destination: url) { Image(systemName: "arrow.up.right.square") }
                        .accessibilityLabel("Open in LCR")
                }
            }
        }
    }

    // MARK: - header

    private var header: some View {
        HStack(spacing: 16) {
            PhotoAvatar(name: member.name, photoURL: member.photoURL, size: 60)
            VStack(alignment: .leading, spacing: 2) {
                Text(member.displayName).font(.title3.bold())
                if let u = member.unitName, !u.isEmpty { Text(u).font(.subheadline).foregroundStyle(.secondary) }
                if let ms = memberSince, !ms.isEmpty { Text(ms).font(.subheadline).foregroundStyle(.secondary) }
                if let demo = demographics { Text(demo).font(.caption).foregroundStyle(.secondary) }
                if let line = baptismLine { Text(line).font(.caption).foregroundStyle(.secondary) }
            }
            Spacer(minLength: 0)
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        // Glass surface matching the section cards below (was a hardcoded indigo fill that didn't adapt
        // to dark mode and clashed with the glass on this most-viewed screen).
        .cpGlassCard()
    }

    // MARK: - rich body (details present)

    @ViewBuilder
    private func richBody(_ d: MemberDetails) -> some View {
        SacramentSection(details: d)
        FriendsSection(details: d, recordedYes: member.friends == "Yes", count: member.friendsCount)
        // Eligibility-gated: hide a section that doesn't APPLY (no priesthood for women, no calling for
        // a child) — but never hide one that has real recorded data.
        if Milestones.priesthoodEligible(member) || !(d.priesthoodOrdinations ?? []).isEmpty {
            ListTextSection(title: "Priesthood Ordination", symbol: "rosette",
                            lines: d.priesthoodOrdinations ?? [],
                            emptyText: "No priesthood ordination on record.")
        }
        if Milestones.callingEligible(member) || !(d.callings ?? []).isEmpty {
            ListTextSection(title: "Calling", symbol: "person.text.rectangle",
                            lines: d.callings ?? [],
                            emptyText: "Not yet been given a calling.",
                            emptyIsAlert: true, recordedYes: member.calling == "Yes")
        }
        if Milestones.ministeringAssignmentEligible(member) || !(d.ministeringAssignments ?? []).isEmpty {
            ListTextSection(title: "Ministering Assignment", symbol: "hands.sparkles",
                            lines: d.ministeringAssignments ?? [],
                            emptyText: "Not yet received a ministering assignment.",
                            recordedYes: member.ministeringAssignment == "Yes")
        }
        NamesSection(title: "Ministering Brothers & Sisters", symbol: "person.3",
                     names: (d.ministeringBrothers ?? []) + (d.ministeringSisters ?? []),
                     emptyText: "No ministers assigned.",
                     recordedYes: member.ministeringBrothersSisters == "Yes")
        TempleSection(details: d)
        PrinciplesSection(details: d)
        TogglesSection(title: "Self-Reliance Classes Completed", symbol: "graduationcap",
                       items: d.selfReliance ?? [])
        TagsSection(tags: d.tags ?? [])
    }

}

// MARK: - completion ring + Record summary

/// Circular completion ring for the Covenant Path header — the arc fills with eligible-only milestone
/// completion and turns solid green with a check at 100%.
struct CompletionRing: View {
    let pct: Double
    var size: CGFloat = 32
    private var clamped: Double { max(0, min(1, pct)) }
    private var done: Bool { pct >= 1 }
    var body: some View {
        let color: Color = done ? Color(hex: 0x2E7D32) : .accentColor
        ZStack {
            Circle().stroke(Color(.separator).opacity(0.5), lineWidth: 3)
            Circle()
                .trim(from: 0, to: clamped)
                .stroke(color, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                .rotationEffect(.degrees(-90))
            if done {
                Image(systemName: "checkmark")
                    .font(.system(size: 13, weight: .bold))
                    .foregroundStyle(Color(hex: 0x2E7D32))
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel("Covenant Path \(Int((clamped * 100).rounded())) percent complete")
    }
}

/// Each tracked status that lacks its own rich section, shown as its OWN section card (like "Attended
/// Sacrament Meeting"): Temple Recommend, Endowment, Patriarchal Blessing. Eligibility-gated (endowment
/// shows "N/A" for the not-yet-eligible). Works from flat fields, so it renders with or without the
/// rich `details` subtree.
struct StatusSections: View {
    let member: Member
    var body: some View {
        if Milestones.templeRecommendEligible(member) {
            StatusSection(title: "Temple Recommend", systemImage: "checkmark.seal",
                          value: recordDisp(member.templeRecommend))
        }
        StatusSection(title: "Endowment", systemImage: "building.columns",
                      value: recordDisp(Milestones.endowmentDisplay(member)))
        if Milestones.patriarchalEligible(member) {
            StatusSection(title: "Patriarchal Blessing", systemImage: "book.closed",
                          value: recordDisp(member.patriarchalBlessing))
        }
    }
}

struct StatusSection: View {
    let title: String
    let systemImage: String
    let value: String
    private var good: Bool { value == "Active" || value == "Yes" }
    var body: some View {
        // Don't show a "not applicable" status card (e.g. Endowment for a not-yet-eligible friend) —
        // an N/A card is noise on the detail page.
        if value == "N/A" {
            EmptyView()
        } else {
            SectionCard(title: title, systemImage: systemImage) {
                Text(value)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(good ? Color(hex: 0x2E7D32) : Color.primary)
            }
        }
    }
}

/// Clean a status value for display: sentinels (needs-profile-api / blocked) → "—" (unknown).
func recordDisp(_ v: String?) -> String {
    let s = v ?? ""
    if s.isEmpty || s == "needs-profile-api" || s.hasPrefix("blocked") { return "—" }
    return s
}

// MARK: - "recorded yes" fallback note

/// When a status field says "Yes" but the (flaky) detail endpoint returned no names, say so instead
/// of "Not yet" — the chip and the section would otherwise contradict each other. Wording matches
/// `_recordedYesNote` (it's a temporary LCR-side data gap, not specific to this person).
struct RecordedYesNote: View {
    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "info.circle").font(.caption)
            Text("Recorded as yes — names are temporarily unavailable from LCR and will appear once "
                 + "its detail data loads on a future sync.")
                .font(.callout)
        }
        .foregroundStyle(Color(hex: 0xFF8F00))   // amber 800
    }
}

func mutedText(_ text: String) -> some View {
    Text(text).foregroundStyle(.secondary)
}

// MARK: - notes / comments (port of `_CommentsSection`)

/// Leader notes on a member (RLS-scoped to people you can see). Read + add. Authors can't see
/// others' across scope boundaries — the DB enforces it.
struct CommentsSection: View {
    let member: Member
    @Environment(\.appServices) private var services
    @Environment(DashboardStore.self) private var store: DashboardStore?

    @State private var comments: [MemberComment] = []
    @State private var loaded = false
    @State private var draft = ""
    @State private var posting = false

    private var uuid: String? { member.personUUID?.isEmpty == false ? member.personUUID : nil }
    private var gateway: SupabaseGateway? { services?.gateway }

    var body: some View {
        if let uuid {
            SectionCard(title: "Notes", systemImage: "bubble.left") {
                VStack(alignment: .leading, spacing: 8) {
                    if !loaded {
                        CardSkeleton(lines: 2)
                    } else if comments.isEmpty {
                        Text("No notes yet.").foregroundStyle(.secondary)
                    } else {
                        ForEach(comments) { c in commentTile(c) }
                    }
                    HStack(alignment: .bottom) {
                        TextField("Add a note…", text: $draft, axis: .vertical)
                            .lineLimit(1...4)
                            .textFieldStyle(.roundedBorder)
                        if posting {
                            ProgressView().controlSize(.small).frame(width: 36, height: 36)
                        } else {
                            Button {
                                Task { await post(uuid: uuid) }
                            } label: {
                                Image(systemName: "paperplane.fill")
                            }
                            .cpGlassButton(prominent: true)
                            .disabled(draft.trimmingCharacters(in: .whitespaces).isEmpty)
                        }
                    }
                }
            }
            .task { await load(uuid: uuid) }
        }
    }

    private func commentTile(_ c: MemberComment) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(c.body ?? "")
            Text("\(c.who) · \(c.createdAt.map(Freshness.exact) ?? "")")
                .font(.caption).foregroundStyle(.secondary)
            Divider().padding(.top, 4)
        }
        .padding(.vertical, 4)
    }

    private func load(uuid: String) async {
        guard let gateway else { loaded = true; return }
        comments = (try? await gateway.comments(memberUUID: uuid)) ?? []
        loaded = true
    }

    private func post(uuid: String) async {
        guard let gateway else { return }
        let body = draft.trimmingCharacters(in: .whitespaces)
        guard !body.isEmpty else { return }
        posting = true
        let email = (await services?.auth.currentEmail) ?? ""
        let new = NewComment(stake_id: member.stakeID, unit_id: member.unitID,
                             member_person_uuid: uuid, author_email: email, body: body)
        do {
            try await gateway.addComment(new)
            draft = ""
            comments = (try? await gateway.comments(memberUUID: uuid)) ?? comments
            await store?.reloadNotes() // list rows show the newest note — keep their index in step
        } catch {
            // surface via the body? keep it simple — leave the draft so they can retry.
        }
        posting = false
    }
}
#endif
