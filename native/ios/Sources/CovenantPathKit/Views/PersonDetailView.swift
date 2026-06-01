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

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 8) {
                header
                // Our covenant-path milestones (data LCR's view lacks).
                SectionCard(title: "Covenant Path", systemImage: "timeline.selection") {
                    GoldenHourChips(member: member, highlightNext: true, labeled: true)
                }
                if let d {
                    richBody(d)
                } else {
                    flatFallback
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
            if let uuid = member.personUUID, !uuid.isEmpty,
               let url = URL(string: "https://lcr.churchofjesuschrist.org/records/member-profile/\(uuid)?lang=eng") {
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
                if let u = member.unitName, !u.isEmpty { Text(u).font(.subheadline) }
                if let ms = memberSince, !ms.isEmpty { Text(ms).font(.subheadline) }
                if let line = baptismLine { Text(line).font(.caption) }
            }
            .foregroundStyle(Color(hex: 0x1A237E))   // on-primaryContainer-ish indigo
            Spacer(minLength: 0)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(hex: 0xC5CAE9).opacity(0.6), in: RoundedRectangle(cornerRadius: 16))
    }

    // MARK: - rich body (details present)

    @ViewBuilder
    private func richBody(_ d: MemberDetails) -> some View {
        SacramentSection(details: d)
        FriendsSection(details: d, recordedYes: member.friends == "Yes", count: member.friendsCount)
        ListTextSection(title: "Priesthood Ordination", symbol: "rosette",
                        lines: d.priesthoodOrdinations ?? [],
                        emptyText: "No priesthood ordination on record.")
        ListTextSection(title: "Calling", symbol: "person.text.rectangle",
                        lines: d.callings ?? [],
                        emptyText: "Not yet been given a calling.",
                        emptyIsAlert: true, recordedYes: member.calling == "Yes")
        ListTextSection(title: "Ministering Assignment", symbol: "hands.sparkles",
                        lines: d.ministeringAssignments ?? [],
                        emptyText: "Not yet received a ministering assignment.",
                        recordedYes: member.ministeringAssignment == "Yes")
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

    // MARK: - flat fallback (pre-`details` rows)

    private var flatFallback: some View {
        let fields: [(String, String?)] = [
            ("Unit", member.unitName), ("Baptism date", member.baptismDate),
            ("Birth date", member.birthDate), ("Friends", member.friends),
            ("Aaronic Priesthood", member.aaronicPriesthood),
            ("Melchizedek Priesthood", member.melchizedekPriesthood),
            ("Calling", member.calling),
            ("Ministering brothers/sisters", member.ministeringBrothersSisters),
            ("Ministering assignment", member.ministeringAssignment),
            ("Temple recommend", member.templeRecommend),
            ("Patriarchal blessing", member.patriarchalBlessing),
            ("Living ordinance", member.livingOrdinance),
        ]
        return VStack(spacing: 0) {
            Divider().padding(.vertical, 8)
            ForEach(fields, id: \.0) { label, value in
                HStack {
                    Text(label)
                    Spacer()
                    Text(value ?? "—").fontWeight(.medium)
                }
                .padding(.vertical, 8)
                Divider()
            }
        }
    }
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
                            .buttonStyle(.borderedProminent)
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
        } catch {
            // surface via the body? keep it simple — leave the draft so they can retry.
        }
        posting = false
    }
}
#endif
