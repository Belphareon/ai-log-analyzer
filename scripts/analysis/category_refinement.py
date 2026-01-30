#!/usr/bin/env python3
"""
Category Refinement - Automatická reklasifikace unknown
=======================================================

Pravidla:
- Jednoduché keyword rules
- Lepší než 90% unknown
- Žádné LLM

Logika:
1. Pokud category == "unknown"
2. Projdi root cause message
3. Aplikuj keyword pravidla
4. Přiřaď novou kategorii

Verze: 6.0
"""

from typing import List, Tuple, Optional, Any
import re


# =============================================================================
# CATEGORY RULES
# =============================================================================

# Pravidla: (pattern_list, new_category, subcategory)
# Pattern může být string nebo regex
CATEGORY_RULES: List[Tuple[List[str], str, str]] = [
    # AUTH
    (
        ['token', 'jwt', 'oauth', 'unauthorized', 'forbidden', 'authentication',
         'credential', 'password', 'login', 'session expired', '401', '403'],
        'auth',
        'authentication_error'
    ),

    # TIMEOUT
    (
        ['timeout', 'timed out', 'deadline exceeded', 'read timed out',
         'connection timed out', 'socket timeout', 'request timeout'],
        'timeout',
        'timeout_error'
    ),

    # DATABASE
    (
        ['sql', 'database', 'db connection', 'jdbc', 'postgres', 'mysql',
         'mongo', 'redis', 'connection pool', 'pool exhausted', 'query failed',
         'deadlock', 'lock wait', 'constraint violation'],
        'database',
        'database_error'
    ),

    # NETWORK
    (
        ['connection refused', 'connection reset', 'network unreachable',
         'host not found', 'dns', 'socket', 'econnreset', 'econnrefused',
         'no route to host', 'connection closed', 'broken pipe'],
        'network',
        'connection_error'
    ),

    # MEMORY
    (
        ['out of memory', 'oom', 'heap space', 'gc overhead', 'memory limit',
         'outofmemoryerror', 'memory allocation', 'stack overflow'],
        'memory',
        'memory_error'
    ),

    # EXTERNAL
    (
        ['external service', 'third party', 'api error', 'upstream',
         'downstream', 'http 5', 'bad gateway', '502', '503', '504'],
        'external',
        'external_service_error'
    ),

    # BUSINESS
    (
        ['validation', 'invalid', 'not found', 'missing', 'required field',
         'constraint', 'business rule', 'insufficient', 'limit exceeded',
         '400', '404', '422'],
        'business',
        'validation_error'
    ),

    # KAFKA/MESSAGING
    (
        ['kafka', 'rabbit', 'amqp', 'message queue', 'consumer', 'producer',
         'offset', 'partition', 'rebalance', 'commit failed'],
        'external',
        'messaging_error'
    ),

    # SSL/TLS
    (
        ['ssl', 'tls', 'certificate', 'handshake', 'x509', 'pkix'],
        'network',
        'ssl_error'
    ),

    # SERIALIZATION
    (
        ['json', 'xml', 'parse', 'serialize', 'deserialize', 'unmarshal',
         'marshal', 'encoding', 'decoding'],
        'business',
        'serialization_error'
    ),
]


def refine_category(
    problem: Any,
    root_cause: Any = None
) -> Tuple[str, str]:
    """
    Zpřesní kategorii problému na základě obsahu.

    Args:
        problem: ProblemAggregate
        root_cause: Volitelný RootCause object

    Returns:
        Tuple[new_category, subcategory]
    """
    # Pokud už má jinou kategorii než unknown, zachovej
    if problem.category != 'unknown':
        return problem.category, getattr(problem, 'subcategory', '')

    # Sesbírej text k analýze
    texts_to_check = []

    # 1. Root cause message
    if root_cause and hasattr(root_cause, 'message'):
        texts_to_check.append(root_cause.message)
        if hasattr(root_cause, 'error_type') and root_cause.error_type:
            texts_to_check.append(root_cause.error_type)

    # 2. Problem normalized message
    if problem.normalized_message:
        texts_to_check.append(problem.normalized_message)

    # 3. Error type
    if problem.error_type:
        texts_to_check.append(problem.error_type)

    # 4. Error class from problem_key
    if problem.error_class and problem.error_class != 'unknown':
        texts_to_check.append(problem.error_class)

    # 5. Sample messages
    for sample in problem.sample_messages[:3]:
        texts_to_check.append(sample)

    # Spojí všechny texty
    combined_text = ' '.join(texts_to_check).lower()

    # Aplikuj pravidla
    for patterns, new_category, subcategory in CATEGORY_RULES:
        for pattern in patterns:
            if pattern.lower() in combined_text:
                return new_category, subcategory

    # Žádné pravidlo nesedí
    return 'unknown', ''


def refine_all_problems(problems: dict) -> dict:
    """
    Zpřesní kategorie všech problémů.

    Args:
        problems: Dict[problem_key, ProblemAggregate]

    Returns:
        Stejný dict s aktualizovanými kategoriemi
    """
    refined_count = 0

    for key, problem in problems.items():
        original_category = problem.category

        # Získej root cause pokud existuje
        root_cause = getattr(problem, 'root_cause', None)

        # Zpřesni kategorii
        new_category, subcategory = refine_category(problem, root_cause)

        if new_category != original_category:
            problem.category = new_category
            problem.subcategory = subcategory
            problem._category_refined = True
            problem._original_category = original_category
            refined_count += 1

    return problems


def get_refinement_stats(problems: dict) -> dict:
    """
    Statistiky reklasifikace.

    Returns:
        {
            'total_refined': int,
            'refinements': {original -> new: count}
        }
    """
    refinements = {}
    total_refined = 0

    for problem in problems.values():
        if hasattr(problem, '_category_refined') and problem._category_refined:
            total_refined += 1
            key = f"{problem._original_category} → {problem.category}"
            refinements[key] = refinements.get(key, 0) + 1

    return {
        'total_refined': total_refined,
        'refinements': refinements,
    }


# =============================================================================
# CUSTOM RULES API
# =============================================================================

def add_category_rule(
    patterns: List[str],
    category: str,
    subcategory: str = ""
):
    """
    Přidá custom pravidlo na začátek seznamu (vyšší priorita).

    Args:
        patterns: Seznam keyword patternů
        category: Nová kategorie
        subcategory: Volitelná subkategorie
    """
    CATEGORY_RULES.insert(0, (patterns, category, subcategory))


def remove_category_rule(category: str):
    """
    Odebere všechna pravidla pro danou kategorii.

    Args:
        category: Kategorie k odebrání
    """
    global CATEGORY_RULES
    CATEGORY_RULES = [r for r in CATEGORY_RULES if r[1] != category]


# =============================================================================
# DOMAIN-SPECIFIC REFINEMENT
# =============================================================================

def refine_with_domain_context(
    problem: Any,
    domain_keywords: dict = None
) -> Tuple[str, str]:
    """
    Zpřesní kategorii s domain-specific kontextem.

    Args:
        problem: ProblemAggregate
        domain_keywords: Dict[keyword, (category, subcategory)]
                        Např: {'card_block': ('business', 'card_block_error')}

    Returns:
        Tuple[new_category, subcategory]
    """
    if not domain_keywords:
        return refine_category(problem)

    # Nejdřív zkus domain-specific pravidla
    texts_to_check = [
        problem.normalized_message or '',
        problem.error_type or '',
        ' '.join(problem.sample_messages[:3])
    ]
    combined = ' '.join(texts_to_check).lower()

    for keyword, (category, subcategory) in domain_keywords.items():
        if keyword.lower() in combined:
            return category, subcategory

    # Fallback na obecná pravidla
    return refine_category(problem)
