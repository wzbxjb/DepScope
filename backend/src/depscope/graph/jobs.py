"""Acquire a write lock before observing mutation lease properties."""


def locked_lease(tx) -> dict:
    row=tx.run("""
        MERGE (l:MutationLease {id:'global'})
        SET l.lock_version=coalesce(l.lock_version,0)+1
        RETURN properties(l) AS lease
        """).single()
    return row["lease"]
