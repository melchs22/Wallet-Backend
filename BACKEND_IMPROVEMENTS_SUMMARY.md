# Backend Improvements Summary

## Overview
This document summarizes the improvements made to the wallet backend to enhance user experience with phone number-based transactions, transaction approval workflows, QR code scanning for bill splitting, and automatic daily limit resets.

## Changes Implemented

### 1. User Model Enhancements
- **Added `primary_phone_number` field** to User model
  - Stores the user's primary phone number for transfers and payments
  - Unique constraint to prevent duplicates
  - Added to UserSerializer and ProfileUpdateSerializer
- **Added `default_provider` field** to Wallet model
  - Defaults to 'orange_money' for new accounts
  - Stores the user's preferred mobile money provider
  - Added to WalletSerializer

### 2. Account Creation Updates
- **Email signup**: Now accepts both `phone_number` and `primary_phone_number` fields
- **Google OAuth**: Updated to create wallets with default Orange Money provider
- **Profile updates**: Users can now set/update their primary phone number in their profile

### 3. Phone Number-Based Transactions
- **Money transfers**: Changed from handle-based to phone number-based
  - Updated `TransferRequestSerializer` to use `recipient_phone` instead of `recipient_handle`
  - Updated transfer logic to resolve recipients by `primary_phone_number`
  - Updated all error logging and audit trails to use phone numbers
- **Payment requests**: Changed from handle-based to phone number-based
  - Updated `PaymentRequestCreateSerializer` to use `payer_phone` instead of `payer_handle`
  - Updated request logic to resolve payers by `primary_phone_number`
- **Bill splitting**: Changed from handle-based to phone number-based
  - Updated `SplitCreateSerializer` to accept phone numbers in participants
  - Updated split creation logic to resolve participants by `primary_phone_number`
  - Updated split detail responses to include phone numbers

### 4. Phone Number Lookup Endpoint
- **New endpoint**: `/api/users/resolve-by-phone`
  - Allows real-time lookup of user details by phone number
  - Returns user ID, handle, display name, avatar, phone number, wallet currency, and default provider
  - Useful for showing user names when entering phone numbers in transfer/request forms
- **Enhanced existing endpoint**: `/api/users/resolve`
  - Now also resolves users by phone number in addition to handle and email

### 5. Transaction Approval Webhook System
- **New model**: `TransactionApproval`
  - Tracks approval requests for money transfers, payment requests, and split bills
  - Stores approval status (pending, approved, declined, expired)
  - Includes expiration dates and webhook delivery tracking
- **Webhook service functions**:
  - `create_transaction_approval()`: Creates approval requests for money transfers
  - `create_payment_request_approval()`: Creates approval requests for payment requests
  - `create_split_approval()`: Creates approval requests for split bill participants
  - `build_transaction_approval_payload()`: Builds webhook payloads
  - `enqueue_transaction_approval_webhook()`: Queues webhook delivery
- **Integration points**:
  - Money transfers now create approval requests for recipients
  - Payment requests create approval requests for payers
  - Split bills create approval requests for participants
  - Webhooks are triggered when approval requests are created

### 6. QR Code Scanning for Bill Splitting
- **New endpoint**: `/api/splits/<split_id>/add-participant-qr`
  - Allows adding participants to split bills by scanning their QR codes
  - Validates QR code signature and expiration
  - Creates payment request and approval for the new participant
  - Updates the split total amount automatically
- **Enhanced split details**: Now includes participant phone numbers and display names

### 7. Daily Transfer Limit Auto-Reset
- **New limit service functions**:
  - `get_daily_sent_amount()`: Calculates total sent today (resets at midnight)
  - `get_daily_remaining()`: Calculates remaining daily limit
- **Business timezone**: Uses Africa/Conakry timezone for daily calculations
- **Auto-reset logic**: Limits automatically reset at midnight in business timezone
- **Updated implementations**:
  - Transfer limit checks now use the new daily calculation functions
  - Payment request limit checks use the new functions
  - Wallet serializer uses the new functions for remaining limit display
  - Scheduled transfer limit checks use the new functions

## Database Migrations
- **Migration 0020**: Added `primary_phone_number` to User model and `default_provider` to Wallet model
- **Migration 0021**: Created `TransactionApproval` model for approval tracking

## API Changes

### Updated Endpoints
- `POST /api/transfers` - Now uses `recipient_phone` instead of `recipient_handle`
- `POST /api/requests/create` - Now uses `payer_phone` instead of `payer_handle`
- `POST /api/splits` - Participants now use `phone` instead of `handle`
- `GET /api/users/resolve` - Now resolves by phone number as well
- `PATCH /api/me` - Now allows updating `primary_phone_number`

### New Endpoints
- `GET /api/users/resolve-by-phone` - Resolve user by phone number specifically
- `POST /api/splits/<split_id>/add-participant-qr` - Add split participant via QR code

## Testing
- System check passed with no issues
- All migrations applied successfully
- Database schema updated correctly

## Frontend Integration Notes
1. **Update transfer forms**: Change from handle input to phone number input
2. **Add phone lookup**: Implement real-time user lookup when phone number is entered
3. **Update request forms**: Change from handle input to phone number input
4. **Update split forms**: Change participant input to phone number with QR code option
5. **Implement approval UI**: Add modals/prompts for transaction approvals
6. **Add webhook listeners**: Set up webhook endpoints to receive approval notifications
7. **Update profile UI**: Add primary phone number field to profile settings

## Security Considerations
- Phone numbers are unique and indexed to prevent duplicates
- Approval requests have expiration dates (default 7 days)
- Webhook signatures are validated for security
- QR code signatures are verified before processing
- All sensitive operations require authentication

## Performance Considerations
- Phone number lookups are indexed for fast queries
- Daily limit calculations use timezone-aware date filtering
- Webhook delivery is asynchronous via Celery tasks
- Approval records include indexes for efficient querying

## Future Enhancements
- Add phone number verification (SMS verification)
- Implement approval response endpoints (approve/decline)
- Add webhook retry logic with exponential backoff
- Add approval notification preferences (push, email, SMS)
- Implement QR code generation for users' profiles
- Add batch approval for multiple requests