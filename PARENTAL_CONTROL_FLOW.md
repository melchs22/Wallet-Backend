# Parental Control Flow Documentation

## Overview
The parental control feature allows parents to link their child's account to monitor and control their spending. The system uses an approval-based flow with PIN confirmation for security.

## How It Works

### 1. Parent Initiates Link Request
- **Who**: Parent user
- **Action**: Parent enters child's phone number in the parental control section
- **API Endpoint**: `POST /api/parental/link`
- **Request Body**:
  ```json
  {
    "child_phone": "+1234567890"
  }
  ```

### 2. System Creates Approval Request
- **Backend Action**: 
  - Validates child account exists and is active
  - Checks if already linked or has existing parent
  - Creates a `TransactionApproval` record with type `parental_link`
  - Creates a pending `ParentalControl` record
  - Sends notification to child user

- **Response to Parent**:
  ```json
  {
    "status": "pending_approval",
    "approval_id": 123,
    "message": "Child will receive a notification to approve the parental link"
  }
  ```

### 3. Child Receives Notification
- **Mechanism**: In-app polling (every 10 seconds)
- **Notification Type**: `parental_link_requested`
- **Notification Payload**:
  ```json
  {
    "approval_id": 123,
    "parent_handle": "parent_user",
    "parent_display_name": "Parent Name",
    "parental_control_id": 456
  }
  ```

### 4. Child Approves/Declines with PIN
- **Child Action**: 
  - Opens notifications
  - Sees parental link request
  - Taps "Approve" or "Decline"
  - Enters 4-digit PIN for confirmation

- **API Endpoints**:
  - Approve: `POST /api/approvals/{approval_id}/approve`
  - Decline: `POST /api/approvals/{approval_id}/decline`

- **Request Body**:
  ```json
  {
    "pin": "1234"
  }
  ```

### 5. Backend Processes Approval
- **If Approved**:
  - Verifies child's PIN
  - Updates `ParentalControl` status from `PENDING` to `ACTIVE`
  - Sets `linked_at` timestamp
  - Updates `TransactionApproval` status to `APPROVED`
  - Sends confirmation notification to parent

- **If Declined**:
  - Verifies child's PIN
  - Updates `ParentalControl` status to `REVOKED`
  - Updates `TransactionApproval` status to `DECLINED`
  - Sends notification to parent

## Parental Permissions

Once linked, the parent can control the following permissions:

### Available Permissions
- **can_view_transactions**: View child's transaction history
- **can_control_balance**: View and manage child's wallet balance
- **can_send_money**: Send money to child's account
- **can_set_limits**: Set spending limits for child

### Updating Permissions
- **API Endpoint**: `POST /api/parental/{control_id}/permissions`
- **Request Body**:
  ```json
  {
    "can_view_transactions": true,
    "can_control_balance": false,
    "can_send_money": true,
    "can_set_limits": true
  }
  ```

## Parental Features

### 1. View Child's Balance
- **Endpoint**: `GET /api/parental/{child_id}/balance`
- **Requirement**: `can_view_transactions` permission
- **Response**:
  ```json
  {
    "balance": "5000.00",
    "currency": "GNF"
  }
  ```

### 2. View Child's Transactions
- **Endpoint**: `GET /api/parental/{child_id}/transactions`
- **Requirement**: `can_view_transactions` permission
- **Response**: List of child's transactions (last 50)

### 3. Send Money to Child
- **Endpoint**: `POST /api/parental/{child_id}/send`
- **Requirement**: `can_send_money` permission
- **Request Body**:
  ```json
  {
    "amount": "1000",
    "note": "Weekly allowance"
  }
  ```

### 4. Revoke Parental Control
- **Endpoint**: `POST /api/parental/{control_id}/revoke`
- **Action**: Parent can revoke the link at any time
- **Result**: `ParentalControl` status set to `REVOKED`

## Security Features

### 1. PIN Verification
- All approval actions require 4-digit PIN
- PIN must be set in user profile
- PIN is hashed using Django's password hashing

### 2. One-Time Approval
- Each parental link request creates a unique approval ID
- Once approved/declined, cannot be reused
- Expired approvals are automatically rejected

### 3. Permission Checks
- All parental actions check for required permissions
- Backend validates parent-child relationship
- Child cannot have multiple active parents

## User Flow Summary

### For Parents:
1. Navigate to Parental Controls section
2. Enter child's phone number
3. Wait for child to approve (via notification)
4. Once approved, configure permissions
5. Monitor child's activity (if permitted)
6. Send money or set limits (if permitted)

### For Children:
1. Receive notification about parental link request
2. Open notification to see details
3. Enter PIN to approve or decline
4. If approved, parent can now monitor/control account
5. Can view parent's permissions at any time

## Error Handling

### Common Errors:
- **User not found**: Child phone number doesn't exist
- **Already linked**: Account already has this parent
- **Has parent**: Child already has an active parental control
- **No PIN set**: User must set transaction PIN first
- **Incorrect PIN**: PIN verification failed
- **Approval expired**: Approval request timed out

### Error Responses:
```json
{
  "error": "Error message description"
}
```

## Database Models

### ParentalControl
- `parent`: User (ForeignKey)
- `child`: User (ForeignKey)
- `status`: PENDING, ACTIVE, REVOKED
- `can_view_transactions`: Boolean
- `can_control_balance`: Boolean
- `can_send_money`: Boolean
- `can_set_limits`: Boolean
- `linked_at`: DateTime
- `verification_code`: String (deprecated, no longer used)

### TransactionApproval
- `approver`: User (child in parental link)
- `requester`: User (parent in parental link)
- `approval_type`: 'parental_link'
- `status`: PENDING, APPROVED, DECLINED, EXPIRED
- `responded_at`: DateTime
- `expires_at`: DateTime
