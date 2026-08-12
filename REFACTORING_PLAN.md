# Code Refactoring Plan

## Overview
This document outlines the refactoring strategy for the German Language Learning Telegram Bot.

## Current State
- Total: ~8000+ lines of Python code
- Main components: bot.py, handlers/, database/, services/, tests/
- Architecture: Partial repository pattern (database layer), monolithic handlers

## Key Issues

### 1. Large Files (Violation of Single Responsibility Principle)
- `handlers/story_handlers.py`: 1260 lines
- `database/db_legacy.py`: 1716 lines  
- `handlers/callback_router.py`: 482 lines
- `handlers/menus.py`: 617 lines
- `handlers/quiz_handlers.py`: 752 lines

### 2. Tight Coupling
- Handlers directly import and use global service instances
- Heavy reliance on `context.user_data` dictionary with string keys
- No clear separation between business logic and presentation

### 3. Code Duplication
- Similar callback handling patterns repeated
- Menu keyboard construction duplicated
- Error handling patterns inconsistent

### 4. Global State Management
- SESSION_KEYS set with 70+ string keys
- No type safety for user data access
- Magic strings throughout the codebase

### 5. Complex Callback Router
- EXACT_ROUTES dict with 40+ entries
- PREFIX_ROUTES list with 20+ entries
- Lambda functions make debugging difficult

## Refactoring Strategy

### Phase 1: Foundation (High Priority)
1. **Create Session Data Classes**
   - Replace magic strings with typed dataclasses
   - Provide type-safe access to session state
   - Location: `models/session_models.py`

2. **Extract Common Handler Utilities**
   - Create base handler classes
   - Extract common error handling
   - Location: `handlers/base.py`

3. **Improve Callback Routing**
   - Use class-based routing instead of lambdas
   - Add better logging and error messages
   - Location: `handlers/routing.py`

### Phase 2: Handler Refactoring (Medium Priority)
4. **Break Down Large Handlers**
   - Split story_handlers into: story_view, story_quiz, story_audio
   - Split quiz_handlers into: quiz_setup, quiz_session, quiz_review
   - Split menus into sub-menus

5. **Introduce Service Layer Abstraction**
   - Create interfaces for services
   - Reduce direct database access in handlers
   - Location: `services/interfaces.py`

### Phase 3: Database Cleanup (Lower Priority)
6. **Complete Repository Migration**
   - Remove legacy db methods
   - Move all methods to appropriate repositories
   - Remove `__getattr__` fallback

7. **Add Unit of Work Pattern**
   - Better transaction management
   - Location: `database/unit_of_work.py`

### Phase 4: Testing & Quality (Ongoing)
8. **Improve Test Coverage**
   - Add integration tests
   - Mock external services
   - Location: `tests/integration/`

9. **Add Type Hints**
   - Gradually add type annotations
   - Use mypy for validation

## Immediate Actions (This Refactoring Session)

### 1. Create Session Models
Create typed dataclasses for session state management to replace magic strings.

### 2. Extract Base Handler
Create a base handler class with common functionality.

### 3. Simplify Callback Router
Refactor the routing mechanism to be more maintainable.

### 4. Improve Error Handling
Standardize error handling across handlers.

### 5. Add Constants
Replace magic strings with constants.

## Success Metrics
- Reduced file sizes (target: max 500 lines per file)
- Increased test coverage (target: 80%+)
- Reduced cyclomatic complexity
- Better type safety
- Improved code readability
