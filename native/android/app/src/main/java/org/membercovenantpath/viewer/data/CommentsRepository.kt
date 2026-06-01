package org.membercovenantpath.viewer.data

import io.github.jan.supabase.SupabaseClient
import io.github.jan.supabase.postgrest.postgrest
import io.github.jan.supabase.postgrest.query.Columns
import io.github.jan.supabase.postgrest.query.Order
import org.membercovenantpath.viewer.model.Comment
import org.membercovenantpath.viewer.model.CommentInsert
import org.membercovenantpath.viewer.model.Member

/**
 * Leader notes on a member, backed by `member_comments` (migration 0017). RLS scopes reads/writes to
 * people the signed-in user can already see — the app does no filtering. Ported from
 * person_detail_page.dart `_CommentsSection` (_load / _post).
 */
class CommentsRepository(
    private val client: SupabaseClient = SupabaseClientProvider.client,
    private val auth: AuthRepository = AuthRepository(),
) {
    /** Existing notes for a member, oldest → newest. */
    suspend fun load(personUuid: String): List<Comment> =
        client.postgrest.from("member_comments")
            .select(Columns.raw("author_email, author_name, body, created_at")) {
                filter { eq("member_person_uuid", personUuid) }
                order("created_at", Order.ASCENDING)
            }
            .decodeList<Comment>()

    /** Add a note; the DB stamps author_name + created_at and RLS enforces author_email. */
    suspend fun add(member: Member, body: String) {
        val uuid = member.personUuid ?: return
        client.postgrest.from("member_comments").insert(
            CommentInsert(
                stakeId = member.stakeId,
                unitId = member.unitId,
                memberPersonUuid = uuid,
                authorEmail = auth.currentEmail ?: "",
                body = body,
            ),
        )
    }
}
